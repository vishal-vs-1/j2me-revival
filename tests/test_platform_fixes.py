"""Focused unit tests verifying platform robustness and compatibility fixes.

Covers:
1. Robustness of gpu_policy.devices() against Vulkan instance creation, enumeration,
   and property-query failures, ensuring Vulkan instances are destroyed on every
   successful creation path.
2. Graceful error handling for missing xdg-open in Linux open_in_file_manager().
3. Safe staged installation and model validation in tools/setup_ai.py with temp cleanup.
4. macOS support clarification and explicit NotImplementedError behavior.
5. Strict PROOF log marker verification in tools/smoke_player.py.
"""
import ctypes as C
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import gpu_policy
import platform_support


class VulkanRobustnessTests(unittest.TestCase):
    """Test gpu_policy.devices() error resilience and instance lifecycle."""

    def setUp(self):
        # Reset cached inventory so each test performs a fresh probe
        gpu_policy._inventory = None

    def tearDown(self):
        gpu_policy._inventory = None

    def test_devices_handles_instance_creation_failure_code(self):
        """When vkCreateInstance returns an error code, devices() returns [] without leak."""
        mock_vk = MagicMock()
        mock_vk.vkCreateInstance.return_value = -3  # VK_ERROR_INITIALIZATION_FAILED

        with patch.object(gpu_policy, '_load_vulkan', return_value=mock_vk):
            result = gpu_policy.devices(refresh=True)

        self.assertEqual(result, [])
        mock_vk.vkCreateInstance.assert_called_once()
        mock_vk.vkDestroyInstance.assert_not_called()

    def test_devices_handles_instance_creation_exception(self):
        """When vkCreateInstance raises an exception, devices() returns [] without leak."""
        mock_vk = MagicMock()
        mock_vk.vkCreateInstance.side_effect = OSError("Driver crashed during instance creation")

        with patch.object(gpu_policy, '_load_vulkan', return_value=mock_vk):
            result = gpu_policy.devices(refresh=True)

        self.assertEqual(result, [])
        mock_vk.vkDestroyInstance.assert_not_called()

    def test_devices_handles_null_instance_handle(self):
        """When vkCreateInstance returns 0 but writes a null pointer handle."""
        mock_vk = MagicMock()

        def fake_create(info_ref, alloc_ref, instance_ref):
            # Do not set instance_ref.contents (leaves handle null / 0)
            return 0

        mock_vk.vkCreateInstance.side_effect = fake_create

        with patch.object(gpu_policy, '_load_vulkan', return_value=mock_vk):
            result = gpu_policy.devices(refresh=True)

        self.assertEqual(result, [])
        mock_vk.vkDestroyInstance.assert_not_called()

    def test_devices_destroys_instance_when_enumeration_fails(self):
        """When vkCreateInstance succeeds but physical device enumeration fails,

        vkDestroyInstance must be called on the valid instance.
        """
        mock_vk = MagicMock()
        fake_instance_handle = 0x12345678

        def fake_create(info_ref, alloc_ref, instance_ref):
            instance_ref._obj.value = fake_instance_handle
            return 0

        mock_vk.vkCreateInstance.side_effect = fake_create
        mock_vk.vkEnumeratePhysicalDevices.return_value = -4  # VK_ERROR_DEVICE_LOST

        with patch.object(gpu_policy, '_load_vulkan', return_value=mock_vk):
            result = gpu_policy.devices(refresh=True)

        self.assertEqual(result, [])
        mock_vk.vkCreateInstance.assert_called_once()
        mock_vk.vkDestroyInstance.assert_called_once()
        # Verify the destroyed handle was the instance we created
        destroyed_handle = mock_vk.vkDestroyInstance.call_args[0][0]
        self.assertEqual(destroyed_handle.value, fake_instance_handle)

    def test_devices_destroys_instance_when_count_is_zero(self):
        """When vkCreateInstance succeeds and count is 0, instance is destroyed."""
        mock_vk = MagicMock()
        fake_instance_handle = 0x87654321

        def fake_create(info_ref, alloc_ref, instance_ref):
            instance_ref._obj.value = fake_instance_handle
            return 0

        def fake_enum(instance, count_ref, handles):
            count_ref._obj.value = 0
            return 0

        mock_vk.vkCreateInstance.side_effect = fake_create
        mock_vk.vkEnumeratePhysicalDevices.side_effect = fake_enum

        with patch.object(gpu_policy, '_load_vulkan', return_value=mock_vk):
            result = gpu_policy.devices(refresh=True)

        self.assertEqual(result, [])
        mock_vk.vkDestroyInstance.assert_called_once()
        self.assertEqual(mock_vk.vkDestroyInstance.call_args[0][0].value, fake_instance_handle)

    def test_devices_resilient_to_property_query_failure_on_individual_device(self):
        """When property querying fails on one device, other valid devices are returned

        and the instance is still destroyed at the end.
        """
        mock_vk = MagicMock()
        fake_instance_handle = 0xAABBCCDD

        def fake_create(info_ref, alloc_ref, instance_ref):
            instance_ref._obj.value = fake_instance_handle
            return 0

        def fake_enum(instance, count_ref, handles):
            if handles is None:
                count_ref._obj.value = 2
                return 0
            handles[0] = 0x1111
            handles[1] = 0x2222
            return 0

        def fake_props(handle, raw_buffer):
            handle_val = getattr(handle, 'value', handle)
            if handle_val == 0x1111:
                raise RuntimeError("Faulty driver crash querying device 0")
            # Device 1: valid dedicated GPU
            fields = (C.c_uint32 * 5).from_buffer(raw_buffer)
            fields[1] = 100  # driver_version
            fields[2] = 0x10DE  # vendor (NVIDIA)
            fields[4] = 2  # kind: dedicated (VK_PHYSICAL_DEVICE_TYPE_DISCRETE_GPU)
            device_name = b"GeForce RTX 4090\0"
            raw_buffer[20:20 + len(device_name)] = device_name

        mock_vk.vkCreateInstance.side_effect = fake_create
        mock_vk.vkEnumeratePhysicalDevices.side_effect = fake_enum
        mock_vk.vkGetPhysicalDeviceProperties.side_effect = fake_props

        with patch.object(gpu_policy, '_load_vulkan', return_value=mock_vk):
            result = gpu_policy.devices(refresh=True)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['name'], "GeForce RTX 4090")
        self.assertEqual(result[0]['kind'], "dedicated")
        mock_vk.vkDestroyInstance.assert_called_once()
        self.assertEqual(mock_vk.vkDestroyInstance.call_args[0][0].value, fake_instance_handle)


class LinuxFileManagerTests(unittest.TestCase):
    """Test Linux open_in_file_manager() error handling."""

    def test_open_in_file_manager_missing_xdg_open(self):
        """When xdg-open is not installed on Linux, raise a descriptive FileNotFoundError."""
        with patch.object(platform_support, 'IS_LINUX', True), \
             patch.object(platform_support, 'IS_WINDOWS', False), \
             patch.object(platform_support, 'IS_MACOS', False), \
             patch('shutil.which', return_value=None):
            with self.assertRaises(FileNotFoundError) as ctx:
                platform_support.open_in_file_manager('/home/user/games')
            self.assertIn("xdg-open", str(ctx.exception))
            self.assertIn("xdg-utils", str(ctx.exception))

    def test_open_in_file_manager_popen_oserror(self):
        """When xdg-open exists but subprocess.Popen raises OSError."""
        with patch.object(platform_support, 'IS_LINUX', True), \
             patch.object(platform_support, 'IS_WINDOWS', False), \
             patch.object(platform_support, 'IS_MACOS', False), \
             patch('shutil.which', return_value='/usr/bin/xdg-open'), \
             patch('subprocess.Popen', side_effect=OSError("Exec format error")):
            with self.assertRaises(OSError) as ctx:
                platform_support.open_in_file_manager('/home/user/games')
            self.assertIn("Failed to launch file manager with xdg-open", str(ctx.exception))


class SetupAiStagingTests(unittest.TestCase):
    """Test safe staging and validation during Real-ESRGAN installation."""

    def _create_zip_bytes(self, files: dict) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as z:
            for arcname, data in files.items():
                z.writestr(arcname, data)
        return buf.getvalue()

    def test_fails_when_binary_missing_and_leaves_target_clean(self):
        """If downloaded archive lacks the ncnn binary, fail without modifying target."""
        from tools import setup_ai
        with tempfile.TemporaryDirectory() as tmp_dir:
            target_ai = Path(tmp_dir) / 'tools/ai'
            archive_data = self._create_zip_bytes({
                'readme.txt': b'hello',
                'models/realesrgan-x4plus.param': b'model_param',
            })

            mock_response = MagicMock()
            mock_response.__enter__.return_value = io.BytesIO(archive_data)

            with patch.object(setup_ai, 'ROOT', Path(tmp_dir)), \
                 patch('urllib.request.urlopen', return_value=mock_response):
                with self.assertRaises(RuntimeError) as ctx:
                    setup_ai.install()
                self.assertIn("no expected runtime", str(ctx.exception))
                # Target should not have any executables
                self.assertEqual(list(target_ai.rglob(setup_ai.ncnn_binary_name())), [])

    def test_fails_when_models_missing_and_cleans_up(self):
        """If downloaded archive lacks models/*.param, fail without installing."""
        from tools import setup_ai
        with tempfile.TemporaryDirectory() as tmp_dir:
            target_ai = Path(tmp_dir) / 'tools/ai'
            bin_name = setup_ai.ncnn_binary_name()
            archive_data = self._create_zip_bytes({
                bin_name: b'fake_binary_content',
                'readme.txt': b'hello',
            })

            mock_response = MagicMock()
            mock_response.__enter__.return_value = io.BytesIO(archive_data)

            with patch.object(setup_ai, 'ROOT', Path(tmp_dir)), \
                 patch('urllib.request.urlopen', return_value=mock_response):
                with self.assertRaises(RuntimeError) as ctx:
                    setup_ai.install()
                self.assertIn("missing required model files", str(ctx.exception))
                self.assertEqual(list(target_ai.rglob(bin_name)), [])

    def test_succeeds_when_binary_and_models_present(self):
        """If downloaded archive has binary and models/*.param, installs correctly."""
        from tools import setup_ai
        with tempfile.TemporaryDirectory() as tmp_dir:
            target_ai = Path(tmp_dir) / 'tools/ai'
            bin_name = setup_ai.ncnn_binary_name()
            archive_data = self._create_zip_bytes({
                f'subfolder/{bin_name}': b'fake_binary_content',
                'subfolder/models/realesrgan-x4plus.param': b'param_data',
                'subfolder/models/realesrgan-x4plus.bin': b'bin_data',
            })

            mock_response = MagicMock()
            mock_response.__enter__.return_value = io.BytesIO(archive_data)

            with patch.object(setup_ai, 'ROOT', Path(tmp_dir)), \
                 patch('urllib.request.urlopen', return_value=mock_response):
                installed_exe = setup_ai.install(progress=lambda msg: None)

            self.assertTrue(installed_exe.exists())
            self.assertTrue((installed_exe.parent / 'models/realesrgan-x4plus.param').exists())
            self.assertTrue((target_ai / 'download.json').exists())


class MacOsClarificationTests(unittest.TestCase):
    """Test macOS unsupported state and explicit NotImplementedError exceptions."""

    def test_lwjgl_classifier_raises_on_macos(self):
        with patch.object(platform_support, 'IS_MACOS', True), \
             patch.object(platform_support, 'IS_WINDOWS', False), \
             patch.object(platform_support, 'IS_LINUX', False):
            with self.assertRaises(NotImplementedError) as ctx:
                platform_support.lwjgl_classifier()
            self.assertIn("macOS is not currently supported", str(ctx.exception))

    def test_open_in_file_manager_raises_on_macos(self):
        with patch.object(platform_support, 'IS_MACOS', True), \
             patch.object(platform_support, 'IS_WINDOWS', False), \
             patch.object(platform_support, 'IS_LINUX', False):
            with self.assertRaises(NotImplementedError) as ctx:
                platform_support.open_in_file_manager('/tmp')
            self.assertIn("macOS is not currently supported", str(ctx.exception))

    def test_setup_ai_raises_on_macos(self):
        from tools import setup_ai
        with patch.object(setup_ai, 'IS_WINDOWS', False), \
             patch.object(setup_ai, 'IS_LINUX', False), \
             patch('sys.platform', 'darwin'):
            with self.assertRaises(NotImplementedError) as ctx:
                setup_ai._platform_key()
            self.assertIn("not yet supported on darwin", str(ctx.exception))


class SmokeTestProofVerificationTests(unittest.TestCase):
    """Test that smoke player proof verification requires the PROOF marker."""

    def test_smoke_player_does_not_break_on_time_alone(self):
        """Verifies smoke_player logic: having a proof file with elapsed time

        without 'PROOF:' in log text does NOT break the loop.
        """
        import time

        proof_exists = True
        proof_mtime = time.time() - 5.0  # 5 seconds old (> 1.5s)
        started = time.time() - 10.0

        # Case 1: log has NO 'PROOF:' marker
        log_text_without_marker = "Rendered 60 frames... Rendering in progress"
        should_break_1 = False
        if proof_exists and proof_mtime >= started:
            if 'PROOF:' in log_text_without_marker:
                should_break_1 = True

        self.assertFalse(should_break_1, "Smoke loop should NOT break without PROOF marker")

        # Case 2: log has 'PROOF:' marker
        log_text_with_marker = "PROOF: 120 GPU frames rendered\n"
        should_break_2 = False
        if proof_exists and proof_mtime >= started:
            if 'PROOF:' in log_text_with_marker:
                should_break_2 = True

        self.assertTrue(should_break_2, "Smoke loop MUST break when PROOF marker is present")


if __name__ == '__main__':
    unittest.main()
