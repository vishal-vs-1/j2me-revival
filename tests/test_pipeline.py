import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import time
import zipfile
import threading
from unittest.mock import patch

import numpy as np
from PIL import Image
from engine import Library, ROOT, enhance, image_id, read_manifest


class PipelineTests(unittest.TestCase):
    def test_control_compatibility_is_scoped_to_exact_game(self):
        from engine import runtime_arguments
        mrbean='061f71e5ad66befade2c6d2bbcca1e5a76c4cf9a7782f82cd80ab8a1e4cc56d6'
        mib='f88c716e45bdb6d8d8bac9a2da81f70046b8e39670835eb4b9a8fd679a74e9fd'
        self.assertIn('-Djme.compat.repaintOnShow=on',runtime_arguments(mrbean))
        self.assertIn('-Djme.input.restoreCanvases=p',runtime_arguments(mrbean))
        self.assertIn('-Djme.input.restoreState=p:cT:7',runtime_arguments(mrbean))
        self.assertEqual(runtime_arguments(mib),[])
        self.assertEqual(runtime_arguments('0'*64),[])
    def test_transparent_identity_and_edge_enhancement(self):
        a = np.zeros((3,3,4),np.uint8)
        a[0,1]=a[1,0]=a[1,1]=(255,0,0,255)
        image=Image.fromarray(a)
        result=enhance(image)
        self.assertEqual(result.size,(12,12))
        nearest=image.resize((12,12),Image.Resampling.NEAREST)
        self.assertNotEqual(result.tobytes(),nearest.tobytes(), 'Must actually change pixel-art edges')
        hidden=a.copy(); hidden[2,2]=(21,32,43,0)
        self.assertEqual(image_id(image),image_id(Image.fromarray(hidden)))

    def test_import_cache_runtime_discovery_and_invalid_jar(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'build') as tmp:
            base=Path(tmp); library=Library(base/'lib',base/'rendered')
            try:
                source=base/'demo.jar'
                with zipfile.ZipFile(source,'w') as z:
                    z.writestr('META-INF/MANIFEST.MF','MIDlet-Name: Test\nMIDlet-1: Test,,Test\n')
                    import io
                    png=io.BytesIO(); Image.new('RGBA',(4,5),'red').save(png,format='PNG')
                    z.writestr('../../escape.png',png.getvalue())
                game=library.import_game(source)
                self.assertEqual(game['status'],'Ready')
                folder=library.workspace(game['id'])
                self.assertEqual(game['assets'],1)
                deadline=time.monotonic()+10
                texture=folder/'textures'/f"{image_id(Image.new('RGBA',(4,5),'red'))}.png"
                while not texture.is_file() and time.monotonic()<deadline:
                    time.sleep(0.02)
                self.assertTrue(texture.is_file(),'Background enhancement did not publish the compatibility texture')
                stamp=texture.stat().st_mtime_ns
                self.assertEqual(library.import_game(source)['id'],game['id'])
                self.assertEqual(texture.stat().st_mtime_ns,stamp)
                self.assertFalse((base/'escape.png').exists())
                self.assertEqual(library.asset_service.stats(game['id'])['sources'],1)
                self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),game['id'])
                with self.assertRaises(ValueError): library.import_game(base/'game.jad')
            finally:
                library.asset_service.close()

    def test_folded_manifest(self):
        self.assertEqual(read_manifest(b'MIDlet-Name: Long\r\n  Name\r\n')['MIDlet-Name'].strip(),'Long Name')

    def test_parallel_conversion_is_bounded_and_cache_is_reused(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'build') as tmp:
            base=Path(tmp); library=Library(base/'lib',base/'rendered',workers=2)
            folder=base/'work'; (folder/'original-assets').mkdir(parents=True)
            assets=[]
            for i in range(4):
                image=Image.new('RGBA',(8,8),(i*50,10,20,255))
                key=image_id(image); path=folder/'original-assets'/(key+'.png'); image.save(path)
                assets.append((key,path))
            barrier=threading.Barrier(2,timeout=5)
            lock=threading.Lock(); active=0; maximum=0
            real=library.prepare_asset
            def observed(*args,**kwargs):
                nonlocal active,maximum
                with lock:
                    active+=1; maximum=max(maximum,active)
                try:
                    barrier.wait()
                    return real(*args,**kwargs)
                finally:
                    with lock: active-=1
            with patch.object(library,'prepare_asset',side_effect=observed) as spy:
                self.assertEqual(library.prepare_many(folder,assets,'pixel',2),4)
                self.assertEqual(maximum,2)
                self.assertEqual(library.prepare_many(folder,assets,'pixel',2),0)
                self.assertEqual(spy.call_count,4)

    def test_exact_screen_profile_and_manual_override(self):
        from engine import atomic_json
        from profiles import PROFILES
        with tempfile.TemporaryDirectory(dir=ROOT/'build') as tmp:
            base=Path(tmp); library=Library(base/'lib',base/'rendered')
            identity='061f71e5ad66befade2c6d2bbcca1e5a76c4cf9a7782f82cd80ab8a1e4cc56d6'
            path=library.workspace(identity)/'game.json'
            game={'id':identity,'name':'MrBeanRacer2','width':240,'height':320}
            atomic_json(path,game)
            migrated=library.games()[0]
            self.assertEqual((migrated['width'],migrated['height']),(176,220))
            migrated.update(width=240,height=320,screen_source='manual')
            atomic_json(path,migrated)
            self.assertEqual(library.games()[0]['width'],240)

    def test_background_pause_stops_new_jobs_and_preserves_cache(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'build') as tmp:
            base=Path(tmp);library=Library(base/'lib',base/'rendered');folder=base/'work'
            (folder/'original-assets').mkdir(parents=True);assets=[]
            for i in range(6):
                image=Image.new('RGBA',(8,8),(i*35,10,20,255));key=image_id(image)
                path=folder/'original-assets'/(key+'.png');image.save(path);assets.append((key,path))
            stop=threading.Event();real=library.prepare_asset
            def interrupted(*args,**kwargs):stop.set();return real(*args,**kwargs)
            with patch.object(library,'prepare_asset',side_effect=interrupted):
                done=library.prepare_many(folder,assets,'pixel',2,stop_event=stop)
            self.assertGreaterEqual(done,1);self.assertLessEqual(done,2)
            stop.clear();remaining=library.prepare_many(folder,assets,'pixel',4,stop_event=stop)
            self.assertEqual(done+remaining,6)
            self.assertEqual(library.prepare_many(folder,assets,'pixel',8),0)

    def test_font_policy_saves_smooth_text_without_a_source_whitelist(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'build') as tmp:
            base=Path(tmp);library=Library(base/'lib',base/'rendered');folder=base/'work'
            (folder/'original-assets').mkdir(parents=True)
            image=Image.new('RGBA',(4,4));image.putpixel((1,1),(255,255,255,255));key=image_id(image)
            image.save(folder/'original-assets'/(key+'.png'))
            (folder/'catalogue.json').write_text(json.dumps([{'resource':'FONT.png','image_id':key}]))
            library.prepare_ui_assets(folder)
            with Image.open(folder/'textures-ui'/(key+'.png')) as result:
                self.assertEqual(result.size,(16,16));self.assertTrue(np.any((np.array(result.getchannel('A'))>0)&(np.array(result.getchannel('A'))<255)))
            self.assertFalse((folder/'asset-sources.txt').exists())
            self.assertFalse((folder/'captures'/'sources.txt').exists())


if __name__=='__main__': unittest.main()
