"""Persistent J2ME library and local enhancement pipeline. No cloud services."""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time
import zipfile
import uuid
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED

import numpy as np
from PIL import Image, ImageFilter
from profiles import PROFILES
from runtime_assets.contracts import image_source_id
from runtime_assets.backends import NcnnBackend, PixelBackend
from runtime_assets.contracts import ncnn_recipe, pixel_recipe
from runtime_assets.service import AssetService
from game_storage import GameStorage, validate_game_id
from execution_policy import java_execution_arguments

ROOT = Path(__file__).resolve().parent
LIBRARY = ROOT / 'library'
RENDERED = ROOT / 'rendered-games'
RECIPE = 'scale2x-rgba-v1-4x'
MAX_PIXELS = 4_194_304


def runtime_arguments(game_id, game=None):
    """Apply compatibility flags and select this game's versioned asset recipe."""
    compat=PROFILES.get(game_id,{}).get('runtime_compat',{});args=[]
    if compat.get('repaint_on_show'):args.append('-Djme.compat.repaintOnShow=on')
    if compat.get('restore_movement_canvases'):
        args.append('-Djme.input.restoreCanvases='+','.join(compat['restore_movement_canvases']))
    if compat.get('restore_movement_state'):
        args.append('-Djme.input.restoreState='+compat['restore_movement_state'])
    recipe_key=(game or {}).get('recipe_key')
    if isinstance(recipe_key,str) and len(recipe_key)==64:
        args.append(f'-Djme.recipeKey={recipe_key}')
    return args


def atomic_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    temp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
    os.replace(temp, path)


def image_id(image: Image.Image) -> str:
    return image_source_id(image)


def scale2x(image: Image.Image) -> Image.Image:
    """Eric Johnston/Scale2x edge-aware rule, applied to complete RGBA colours."""
    a = np.array(image.convert('RGBA'), dtype=np.uint8)
    a[a[:, :, 3] == 0] = 0
    p = np.pad(a, ((1, 1), (1, 1), (0, 0)), mode='edge')
    b, d, e, f, h = p[:-2, 1:-1], p[1:-1, :-2], a, p[1:-1, 2:], p[2:, 1:-1]
    eq = lambda x, y: np.all(x == y, axis=2)
    active = ~eq(b, h) & ~eq(d, f)
    result = np.empty((a.shape[0] * 2, a.shape[1] * 2, 4), np.uint8)
    for row, col, x, y in [(0, 0, d, b), (0, 1, b, f), (1, 0, d, h), (1, 1, h, f)]:
        result[row::2, col::2] = np.where((active & eq(x, y))[:, :, None], x, e)
    return Image.fromarray(result)


def enhance(image: Image.Image) -> Image.Image:
    return scale2x(scale2x(image))


def read_manifest(raw: bytes) -> dict:
    text = raw.decode('utf-8', errors='replace').replace('\r\n', '\n')
    lines = []
    for line in text.split('\n'):
        if line.startswith(' ') and lines:
            lines[-1] += line[1:]
        else:
            lines.append(line)
    return dict(line.split(':', 1) for line in lines if ':' in line)


def locate_java(tool='java') -> str:
    override = os.environ.get('JME_JAVA_HOME')
    candidates = [Path(override) / 'bin' / (tool + '.exe')] if override else []
    # Avoid Oracle javapath launcher shims, which can hang on stale installations.
    for base in [Path('C:/Program Files/Java'), Path('C:/Program Files/Eclipse Adoptium')]:
        if base.exists():
            candidates.extend(p / 'bin' / (tool + '.exe') for p in sorted(base.iterdir(), reverse=True))
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    found = shutil.which(tool)
    if found:
        return found
    raise RuntimeError('A Java JDK is required. Install JDK 17 or newer, or set JME_JAVA_HOME.')


class Library:
    def __init__(self, library=LIBRARY, rendered=RENDERED, workers=2):
        self.library, self.rendered = Path(library), Path(rendered)
        self.library.mkdir(parents=True, exist_ok=True)
        self.rendered.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.workers = max(1, min(8, int(workers)))
        self._asset_backends = {}
        self._players = {}
        self._deleting = set()
        self.asset_service = AssetService(self._backend_for_recipe)

    def recipe_for_backend(self, backend):
        if backend == 'pixel':
            return pixel_recipe(), None
        ncnn = NcnnBackend()
        recipe = ncnn.recipe()
        self._asset_backends[recipe.key] = ncnn
        return recipe, recipe

    def _backend_for_recipe(self, recipe):
        if recipe.key in self._asset_backends:
            return self._asset_backends[recipe.key]
        if recipe.algorithm == 'scale2x-rgba':
            backend = PixelBackend(enhance)
        elif recipe.algorithm == 'realesrgan-x4plus-anime':
            backend = NcnnBackend()
            if backend.recipe().key != recipe.key:
                raise RuntimeError('The installed AI model no longer matches this recipe.')
        else:
            raise LookupError(f'No enhancement backend for {recipe.algorithm!r}')
        self._asset_backends[recipe.key] = backend
        return backend

    def games(self):
        result = []
        for file in self.rendered.glob('*/game.json'):
            if file.parent.name.startswith('.') or file.parent.name in self._deleting:continue
            try:
                game=json.loads(file.read_text(encoding='utf-8'))
                profile=PROFILES.get(game['id'])
                if profile and 'width' in profile and not game.get('screen_source') and (game['width'],game['height'])==(240,320):
                    game['previous_screen']=[game['width'],game['height']]
                    game.update(profile)
                    atomic_json(file,game)
                if game.get('ui_recipe')!='smooth-text-v1' and (file.parent/'catalogue.json').exists():
                    self.prepare_ui_assets(file.parent)
                    game['ui_recipe']='smooth-text-v1';atomic_json(file,game)
                from game_inspection import inspect,VERSION as INSPECTION_VERSION
                inspection_file=file.parent/'graphics-inspection.json'
                try:inspection_version=json.loads(inspection_file.read_text()).get('inspection_version',0)
                except (OSError,ValueError):inspection_version=0
                if inspection_version<INSPECTION_VERSION and (self.library/game['id']/'game.jar').exists():
                    try:report=inspect(self.library/game['id']/'game.jar',game.get('assets'))
                    except (OSError,zipfile.BadZipFile) as error:report={'inspection_version':INSPECTION_VERSION,'error':str(error)}
                    atomic_json(inspection_file,report)
                if (file.parent/'graphics-inspection.json').exists():
                    game['graphics_inspection']=json.loads((file.parent/'graphics-inspection.json').read_text())
                result.append(game)
            except (ValueError, OSError):
                pass
        return sorted(result, key=lambda g: g['name'].casefold())

    def workspace(self, game_id):
        return self.rendered / validate_game_id(game_id)

    def save(self, game):
        with self.lock:
            self._check_not_deleting(game['id'])
            atomic_json(self.workspace(game['id']) / 'game.json', game)

    def _check_not_deleting(self,game_id):
        if game_id in self._deleting:raise RuntimeError('This game is being deleted. Wait for deletion to finish before importing or changing it.')

    def delete_game(self,game_id,progress=lambda message:None,*,timeout=60.0):
        """Stop scheduling this game, delete its owned data, and retain saves for reimport."""
        with self.lock:
            self._check_not_deleting(game_id)
            storage=GameStorage(self.library,self.rendered)
            storage.deletion_paths(game_id)
            folder=self.workspace(game_id)
            metadata=json.loads((folder/'game.json').read_text(encoding='utf-8')) if (folder/'game.json').is_file() else None
            player=self._players.get(game_id)
            if player is not None:
                if player.poll() is None:
                    raise RuntimeError('Close the game before deleting it so its saves can finish writing.')
                try:self.asset_service.set_player_state(game_id,False)
                except KeyError:pass
            self._deleting.add(game_id)
        # Waiting and filesystem cleanup never hold the library-wide lock.
        cleanup_started=False
        try:
            progress('Deleting in background; waiting for any current artwork batch…')
            self.asset_service.unregister_game(game_id,timeout=timeout)
            progress('Deleting game files and artwork. Keeping saved progress…')
            cleanup_started=True
            saves=storage.delete(game_id)
            self._players.pop(game_id,None)
            return saves
        except Exception:
            if cleanup_started and metadata and (folder/'game.json').is_file():
                try:
                    # Rebuild archive-derived data and reconcile missing cache
                    # outputs before making a failed deletion playable again.
                    self.decode_assets(metadata)
                    recipe,ai_recipe=self.recipe_for_backend(metadata.get('backend','pixel'))
                    self.asset_service.register_game(folder,recipe,game=metadata,ai_recipe=ai_recipe)
                except Exception:pass
            raise
        finally:
            with self.lock:self._deleting.discard(game_id)

    def prepare_startup(self, game, progress=lambda message: None):
        """Startup cleanup has its own handler/cache, independent of artwork/input."""
        from startup_cleaner import select_startup
        source = self.library / game['id'] / 'game.jar'
        enabled=bool(game.get('remove_startup_wrappers', False))
        playable, report = select_startup(source, self.workspace(game['id']) / 'startup',
            enabled=enabled, javac=locate_java('javac') if enabled else None,
            player=ROOT/'build/jme-player.jar', progress=progress)
        if game.get('startup') != report:
            game['startup'] = report
            game['startup_hint'] = ('Promotional startup screens removed. Starts directly in the game.'
                if report['status'] == 'cleaned' else PROFILES.get(game['id'],{}).get('startup_hint',''))
            self.save(game)
        return playable

    def import_game(self, source, progress=lambda message: None, backend='pixel'):
        source = Path(source).resolve()
        if source.suffix.lower() != '.jar':
            raise ValueError('Select the actual .jar game. A .jad is only its descriptor.')
        if source.stat().st_size > 64 * 1024 * 1024:
            raise ValueError('JAR exceeds the 64 MB experiment limit.')
        identity = hashlib.sha256(source.read_bytes()).hexdigest()
        folder = self.workspace(identity)
        with self.lock:
            self._check_not_deleting(identity)
            existing = folder / 'game.json'
            if existing.exists():
                game = json.loads(existing.read_text(encoding='utf-8'))
                if game.get('status') == 'Ready' and (self.library / identity / 'game.jar').exists():
                    from asset_decoding import VERSION as DECODING_VERSION, default_registry
                    report=game.get('asset_decoding',{})
                    if report.get('version')==DECODING_VERSION and report.get('registry')==[d.name for d in default_registry().decoders]:
                        if game.get('backend') != backend:
                            return self.prepare_style(game, backend, progress)
                        migration_game = dict(game)
                        recipe, ai_recipe = self.recipe_for_backend(game.get('backend', backend))
                        game['recipe_key'] = recipe.key
                        if ai_recipe is not None:
                            game['model_digest'] = recipe.model_digest
                        self.save(game)
                        self.asset_service.register_game(folder, recipe, game=migration_game,
                                                         ai_recipe=ai_recipe)
                        game['asset_work'] = self.asset_service.stats(identity)
                        progress('Already prepared — reusing saved assets.')
                        return game
                    return self.prepare_style(game,game.get('backend',backend),progress)
            with zipfile.ZipFile(source) as archive:
                infos = archive.infolist()
                if len(infos) > 20_000 or sum(i.file_size for i in infos) > 128 * 1024 * 1024:
                    raise ValueError('Archive expands beyond the supported limit.')
                try:
                    manifest = {k: v.strip() for k, v in read_manifest(archive.read('META-INF/MANIFEST.MF')).items()}
                except KeyError:
                    raise ValueError('Not a Java ME game: META-INF/MANIFEST.MF is missing.')
                if 'MIDlet-1' not in manifest:
                    raise ValueError('No MIDlet-1 entry found; this is not a supported Java ME game.')
                folder.mkdir(parents=True, exist_ok=True)
                dest = self.library / identity / 'game.jar'
                dest.parent.mkdir(parents=True, exist_ok=True)
                if source != dest.resolve():
                    shutil.copy2(source, dest)
                for sub in ['original-assets', 'textures', 'logs', 'saves']:
                    (folder / sub).mkdir(exist_ok=True)
                game = {'id': identity, 'name': manifest.get('MIDlet-Name', source.stem),
                        'vendor': manifest.get('MIDlet-Vendor', ''), 'status': 'Preparing',
                        'width': 240, 'height': 320, 'scale': 4, 'recipe': RECIPE if backend == 'pixel' else 'realesrgan-anime-alpha-v1-4x',
                        'backend': backend, 'workers': self.workers,
                        'assets': 0, 'imported': time.time(),
                        'original_filename': source.name, 'manifest': manifest}
                game.update(PROFILES.get(identity,{}))
                self.save(game)
                self.prepare_startup(game, progress)
                report,catalogue = self.decode_assets(game, progress)
                seen={row['image_id'] for row in catalogue}
                self.prepare_ui_assets(folder)
                from game_inspection import inspect
                atomic_json(folder/'graphics-inspection.json',inspect(dest,report['outcomes'].get('standard-images-v1',0)))
                self.record_decoding_coverage(game)
                game.update(status='Ready', assets=len(seen), prepared=time.time(),ui_recipe='smooth-text-v1')
                recipe, ai_recipe = self.recipe_for_backend(backend)
                game['recipe_key'] = recipe.key
                if ai_recipe is not None:
                    game['model_digest'] = recipe.model_digest
                self.save(game)
                migration_game = dict(game)
                if ai_recipe is not None:
                    # Do not attribute pre-existing unindexed AI files to weights
                    # that this fresh import has not yet used.
                    migration_game.pop('model_digest', None)
                migration = self.asset_service.register_game(folder, recipe, game=migration_game,
                                                             ai_recipe=ai_recipe)
                game['asset_work'] = self.asset_service.stats(identity)
                self.save(game)
                progress(f'Ready to play — {len(seen)} sources registered; '
                         f'{migration.jobs_queued} enhancement jobs continue in the background.')
                return game

    def texture_dir(self, folder, backend):
        return folder / ('textures-ai' if backend == 'ai' else 'textures')

    def prepare_ui_assets(self, folder):
        """Smooth bitmap text without asking a neural model to redraw individual letters."""
        catalogue=json.loads((folder/'catalogue.json').read_text(encoding='utf-8'))
        for item in catalogue:
            resource=item['resource'].replace('\\','/').lower()
            if 'font' not in resource:continue
            source=folder/'original-assets'/(item['image_id']+'.png')
            target=folder/'textures-ui'/source.name
            if target.exists():continue
            target.parent.mkdir(parents=True,exist_ok=True)
            with Image.open(source) as image:
                result=image.convert('RGBA').resize((image.width*4,image.height*4),Image.Resampling.LANCZOS)
                result.save(target)

    def prepare_asset(self, folder, key, image, backend='pixel'):
        target = self.texture_dir(folder, backend) / (key + '.png')
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            return False
        ui=folder/'textures-ui'/(key+'.png')
        if ui.exists():
            shutil.copy2(ui,target);return True
        if not (folder / 'original-assets' / (key + '.png')).exists():
            image.save(folder / 'original-assets' / (key + '.png'))
        enhanced = enhance(image)
        if backend == 'ai':
            from ai_backend import upscale
            enhanced = upscale(image, folder, enhanced.getchannel('A'))
        temp = target.with_suffix('.tmp')
        enhanced.save(temp, format='PNG')
        os.replace(temp, target)
        return True

    def prepare_many(self, folder, assets, backend, workers, progress=lambda msg: None, stop_event=None):
        """Bound both running work and decoded images; cached entries are never resubmitted."""
        jobs = [(key,path) for key,path in assets if not (self.texture_dir(folder,backend)/(key+'.png')).exists()]
        workers = max(1,min(8,int(workers)))
        if not jobs:
            progress('All artwork is already cached — no conversion needed.')
            return 0
        progress(f'Enhancing {len(jobs)} images with {workers} parallel workers ({backend})…')
        def convert(job):
            key,path=job
            with Image.open(path) as decoded:
                if decoded.width*decoded.height>MAX_PIXELS:
                    raise ValueError('Image exceeds the supported dimensions')
                image=decoded.convert('RGBA')
            return self.prepare_asset(folder,key,image,backend)
        count=0
        iterator=iter(jobs)
        with ThreadPoolExecutor(max_workers=workers,thread_name_prefix='asset') as pool:
            pending=set()
            for _ in range(workers):
                if stop_event is not None and stop_event.is_set():break
                job=next(iterator,None)
                if job is not None:pending.add(pool.submit(convert,job))
            completed=0
            while pending:
                ready,pending=wait(pending,return_when=FIRST_COMPLETED)
                for future in ready:
                    count+=bool(future.result())
                    completed+=1
                    progress(f'Enhanced {completed}/{len(jobs)} images • up to {workers} in parallel')
                    job=next(iterator,None) if stop_event is None or not stop_event.is_set() else None
                    if job is not None: pending.add(pool.submit(convert,job))
        return count

    def prepare_style(self, game, backend, progress=lambda msg: None):
        folder = self.workspace(game['id'])
        with self.lock:
            self._check_not_deleting(game['id'])
            self.decode_assets(game, progress)
            self.prepare_ui_assets(folder)
            self.record_decoding_coverage(game)
            current=json.loads((folder/'game.json').read_text(encoding='utf-8'))
            migration_game = dict(current)
            migration_game['asset_decoding'] = game.get('asset_decoding', {})
            current.pop('packed_decoder',None)
            for key in ('decoded_assets', 'decoded_scope', 'decoded_packs_reached',
                        'decoded_packs_total', 'runtime_assets'):
                current.pop(key, None)
            current.update(backend=backend, recipe=RECIPE if backend=='pixel' else 'realesrgan-anime-alpha-v1-4x')
            for key in ('assets','asset_decoding'):
                if key in game:current[key]=game[key]
            recipe, ai_recipe = self.recipe_for_backend(backend)
            current['recipe_key'] = recipe.key
            if ai_recipe is not None:
                current['model_digest'] = recipe.model_digest
            else:
                current.pop('model_digest', None)
            self.save(current)
            self.asset_service.register_game(folder, recipe, game=migration_game,
                                             ai_recipe=ai_recipe)
            current['asset_work'] = self.asset_service.stats(game['id'])
            self.save(current)
            progress('Artwork work was queued. The game is ready to play while conversion continues.')
            return current

    def decode_assets(self, game, progress=lambda msg: None):
        from asset_decoding import decode_jar
        folder=self.workspace(game['id'])
        report,catalogue=decode_jar(self.library/game['id']/'game.jar',folder,image_id,
                                    locate_java(),ROOT/'build/jme-player.jar',progress)
        game['asset_decoding']=report
        game['assets']=report['unique_images']
        return report,catalogue

    def enhance_sources(self, game, backend, sources, progress=lambda msg: None):
        folder=self.workspace(game['id'])
        return self.prepare_many(folder,sources,backend,game.get('workers',self.workers),progress)

    def record_decoding_coverage(self, game):
        folder=self.workspace(game['id'])
        inspection=folder/'graphics-inspection.json'
        if inspection.is_file():
            report=json.loads(inspection.read_text(encoding='utf-8'))
            report.setdefault('handling_plan',{})['source_decoding']=game.get('asset_decoding',{})
            report['handling_plan']['complete_hd_coverage']=None
            report['coverage_note']=game.get('asset_decoding',{}).get('coverage',
                'runtime coverage is not yet measured')
            atomic_json(inspection,report)

    def launch(self, game, original=False, proof=None, *, stop_seconds=0, hidden=False):
        with self.lock:
            self._check_not_deleting(game['id'])
            return self._launch(game,original,proof,stop_seconds=stop_seconds,hidden=hidden)

    def _launch(self, game, original=False, proof=None, *, stop_seconds=0, hidden=False):
        if game.get('status') != 'Ready':
            raise RuntimeError('This import has not finished. Import the JAR again to resume.')
        emulator = ROOT / 'build' / 'jme-player.jar'
        if not emulator.exists():
            raise RuntimeError('Player is not built. Run python tools/build.py first.')
        folder = self.workspace(game['id'])
        playable = self.prepare_startup(game)
        log_path = folder / 'logs' / f'play-{time.time_ns()}.log'
        scale = max(1, min(4, 900 // game['height']))
        render_scale=max(2,min(4,int(game.get('render_scale',4))))
        from gpu_policy import settings,player_java,expected_device
        gpu_mode=settings()['render_gpu']
        java=player_java(gpu_mode) if game.get('renderer','gpu')=='gpu' else locate_java()
        expected=expected_device(gpu_mode) if game.get('renderer','gpu')=='gpu' else None
        args = [java, *java_execution_arguments(game), '-Xmx768m', '-Dfile.encoding=ISO_8859_1', f'-Djme.pack={folder}',
                f'-Djme.stats={log_path.with_suffix(".stats.json")}',
                f"-Djme.textures={self.texture_dir(folder,game.get('backend','pixel'))}",
                f'-Djme.scale={1 if original else render_scale}']
        args += [f'-Djme.gpuPreference={gpu_mode}',f'-Djme.expectedGpu={expected["name"] if expected else ""}']
        args += runtime_arguments(game['id'],game)
        if game.get('renderer','gpu')=='gpu':
            if not list((ROOT/'tools/gpu').glob('lwjgl-*.jar')):
                raise RuntimeError('GPU runtime is missing. Run python tools/setup_gpu.py first.')
            args += ['--enable-native-access=ALL-UNNAMED','-Djme.gpu=true','-cp',str(emulator)+os.pathsep+str(ROOT/'tools/gpu/*'),
                     'org.recompile.mobile.GpuPlayer',str(playable),str(game['width']),str(game['height']),game['name']]
        else:
            args += ['-jar',str(emulator),playable.resolve().as_uri(),'1',str(game['width']),str(game['height']),str(scale)]
        if proof:
            args.insert(1, f'-Djme.proof={Path(proof).resolve()}')
        if stop_seconds:args.insert(1,f'-Djme.stopSeconds={int(stop_seconds)}')
        if hidden:args.insert(1,'-Djme.hidden=true')
        with log_path.open('w', encoding='utf-8') as log:
            log.write('Startup: '+str(playable)+'\n')
            log.write(game['startup']['note']+'\n')
            log.flush()
            process = subprocess.Popen(args, cwd=folder / 'saves', stdout=log, stderr=subprocess.STDOUT)
        self._players[game['id']]=process
        return process, log_path
