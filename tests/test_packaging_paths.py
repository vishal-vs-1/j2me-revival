"""Portable resources, downloaded AI and saves must survive layout changes."""
import io
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile


ROOT = Path(__file__).resolve().parents[1]


class PackagingPathsTests(unittest.TestCase):
    def test_source_checkout_keeps_existing_data_locations(self):
        with patch.object(sys, 'frozen', False, create=True):
            paths = runpy.run_path(str(ROOT / 'app_paths.py'))
        self.assertEqual(paths['RESOURCE_ROOT'], ROOT)
        self.assertEqual(paths['DATA_ROOT'], ROOT)

    def test_frozen_modules_agree_on_resources_saves_and_ai_location(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'build', prefix='portable paths ') as folder:
            command = """
import sys
from pathlib import Path
home = Path(sys.argv[1]).resolve()
sys.frozen = True
sys.executable = str(home / 'JAR Revival.exe')
sys._MEIPASS = str(home / 'app')
import app_paths, engine, app, gpu_policy, ai_backend
from tools import setup_ai
assert app_paths.APP_ROOT == home
assert engine.ROOT == home / 'app'
assert app.ROOT / 'fixtures/RevivalDemo.jar' == home / 'app/fixtures/RevivalDemo.jar'
assert gpu_policy.ROOT == home / 'app'
assert engine.LIBRARY == home / 'data/library'
assert engine.RENDERED == home / 'data/rendered-games'
assert gpu_policy.SETTINGS == home / 'data/library/settings.json'
assert setup_ai.ROOT == ai_backend.ROOT == home / 'data'
"""
            result = subprocess.run([sys.executable, '-c', command, folder], cwd=ROOT,
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_ai_install_and_lookup_use_same_data_folder_without_repeat_download(self):
        from tools import setup_ai
        import ai_backend
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            archive.writestr('runtime/realesrgan-ncnn-vulkan.exe', b'fixture executable')
            archive.writestr('runtime/models/realesrgan-x4plus-anime.param', b'fixture model')
        with tempfile.TemporaryDirectory(dir=ROOT / 'build') as folder:
            data = Path(folder) / 'data'
            with patch.object(setup_ai, 'ROOT', data), patch.object(ai_backend, 'ROOT', data), \
                 patch.object(setup_ai.urllib.request, 'urlopen', return_value=io.BytesIO(buffer.getvalue())) as download:
                executable = setup_ai.install(lambda message: None)
                self.assertEqual(executable, ai_backend.executable())
                self.assertTrue(executable.is_relative_to(data / 'tools/ai'))
                self.assertTrue((executable.parent / 'models/realesrgan-x4plus-anime.param').is_file())
                self.assertEqual(setup_ai.install(lambda message: None), executable)
                download.assert_called_once()
