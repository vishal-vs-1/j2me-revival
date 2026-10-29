import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from engine import Library, ROOT, locate_java
from startup_cleaner import MRBEAN, prepare_startup, select_startup, digest


class StartupTests(unittest.TestCase):
    def test_unknown_wrapper_stays_intact_even_when_option_enabled(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'build') as work:
            work=Path(work);source=work/'unknown.jar'
            with zipfile.ZipFile(source,'w') as jar:
                jar.writestr('META-INF/MANIFEST.MF','MIDlet-1: Test,,Unknown\n')
                jar.writestr('Unknown.class',b'not bytecode; http://www.mobilerated.com')
            before=source.read_bytes()
            playable,report=select_startup(source,work/'startup',enabled=True)
            self.assertEqual(playable,source)
            self.assertEqual(report['status'],'unrecognized_wrapper')
            self.assertEqual(source.read_bytes(),before)
            self.assertFalse((work/'startup/playable.jar').exists())

    @unittest.skipUnless((ROOT/'library'/MRBEAN/'game.jar').exists(),'Local game fixture required')
    def test_verified_repair_is_optional_preserves_game_and_reuses_cache(self):
        source=ROOT/'library'/MRBEAN/'game.jar'
        original=source.read_bytes()
        with tempfile.TemporaryDirectory(dir=ROOT/'build') as work:
            work=Path(work)
            # Merely detecting a known wrapper must never compile or remove it.
            with patch('startup_cleaner.subprocess.run',side_effect=AssertionError('Unexpected cleanup')):
                default,report=select_startup(source,work/'startup')
            self.assertEqual(default,source)
            self.assertEqual(report['status'],'verified_wrapper')
            self.assertFalse((work/'startup').exists())
            playable,report=prepare_startup(source,work/'startup',javac=locate_java('javac'),player=ROOT/'build/jme-player.jar')
            self.assertEqual(report['status'],'cleaned')
            self.assertEqual(len(report['removed_classes']),25)
            with zipfile.ZipFile(source) as old,zipfile.ZipFile(playable) as new:
                self.assertEqual({n for n in new.namelist() if n.endswith('.class')},{'a.class','o.class','p.class','WRAPPER.class'})
                for name in new.namelist():
                    if name!='WRAPPER.class':self.assertEqual(old.read(name),new.read(name),name)
            stamp=playable.stat().st_mtime_ns
            with patch('startup_cleaner.subprocess.run',side_effect=AssertionError('Recompiled cached game')):
                reused,_=select_startup(source,work/'startup',enabled=True)
                restored,_=select_startup(source,work/'startup',enabled=False)
            self.assertEqual(reused,playable);self.assertEqual(restored,source)
            self.assertEqual(playable.stat().st_mtime_ns,stamp)
            self.assertEqual(source.read_bytes(),original)
            self.assertEqual(hashlib.sha256(original).hexdigest(),MRBEAN)

    def test_both_players_use_original_by_default_and_optional_selected_path(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'build') as work:
            work=Path(work);library=Library(work/'library',work/'rendered')
            app_root=work/'app'
            (app_root/'build').mkdir(parents=True)
            (app_root/'build'/'jme-player.jar').touch()
            gpu_runtime=app_root/'tools'/'gpu'
            gpu_runtime.mkdir(parents=True)
            (gpu_runtime/'lwjgl-test.jar').touch()
            game={'id':'0'*64,'name':'Test','status':'Ready','width':176,'height':220,
                  'startup':{'note':'Diagnostic startup selection'}}
            folder=library.workspace(game['id']);(folder/'logs').mkdir(parents=True);(folder/'saves').mkdir()
            chosen=work/'selected.jar'
            for renderer in ['gpu','cpu']:
                game['renderer']=renderer
                with patch('engine.ROOT',app_root),patch.object(library,'prepare_startup',return_value=chosen),patch('engine.subprocess.Popen') as launch,\
                     patch('gpu_policy.player_java',return_value=locate_java()),patch('gpu_policy.expected_device',return_value=None):
                    library.launch(game)
                    arguments=launch.call_args.args[0]
                    self.assertIn(str(chosen) if renderer=='gpu' else chosen.as_uri(),arguments)
                    self.assertNotIn('-Xint',arguments)
                    self.assertNotIn('-XX:TieredStopAtLevel=1',arguments)
                    game['execution_mode']='interpreted'
                    library.launch(game)
                    compatible=launch.call_args.args[0]
                    self.assertEqual(compatible.count('-XX:TieredStopAtLevel=1'),1)
                    self.assertNotIn('-Xint',compatible)
                    stable=lambda args:[arg for arg in args if arg!='-XX:TieredStopAtLevel=1' and not arg.startswith('-Djme.stats=')]
                    self.assertEqual(stable(compatible),stable(arguments))
                    game.pop('execution_mode')


if __name__=='__main__':unittest.main()
