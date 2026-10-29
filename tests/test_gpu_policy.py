import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import gpu_policy as gpu

class GpuPolicyTests(unittest.TestCase):
    def setUp(self):
        self.devices=[{'index':0,'kind':'integrated','name':'AMD Radeon'},
                      {'index':1,'kind':'dedicated','name':'NVIDIA RTX 2050'}]
    def test_auto_prefers_dedicated_and_falls_back_when_absent(self):
        self.assertEqual(gpu.choose_device('auto',self.devices)['index'],1)
        self.assertEqual(gpu.choose_device('auto',self.devices[:1])['index'],0)
        self.assertIsNone(gpu.choose_device('auto',[]))
        self.assertIsNone(gpu.choose_device('system',self.devices))
    def test_explicit_class_and_missing_device(self):
        self.assertEqual(gpu.choose_device('integrated',self.devices)['index'],0)
        with self.assertRaises(RuntimeError):gpu.choose_device('dedicated',self.devices[:1])
        with self.assertRaises(ValueError):gpu.choose_device('invalid',self.devices)
    def test_settings_and_inference_id_are_independent(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'build') as folder:
            with patch.object(gpu,'SETTINGS',Path(folder)/'settings.json'),patch.object(gpu,'devices',return_value=self.devices):
                self.assertEqual(gpu.settings()['render_gpu'],'auto')
                gpu.save_settings(render_gpu='integrated',enhance_gpu='dedicated')
                self.assertEqual(gpu.settings()['render_gpu'],'integrated')
                args,device=gpu.inference_arguments();self.assertEqual(args,['-g','1'])
                gpu.save_settings(enhance_gpu='integrated')
                self.assertEqual(gpu.inference_arguments()[0],['-g','0'])
                self.assertEqual(gpu.settings()['render_gpu'],'integrated')
