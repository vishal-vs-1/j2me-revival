"""Unit tests verifying measured DPI scaling, dynamic XWayland detection, and fallback layers."""
from unittest.mock import MagicMock, patch
import sys
import unittest

import window_scaling


class WindowScalingTests(unittest.TestCase):
    """Test scaling logic across 100%, 125%, HiDPI, mixed-monitors, and fallback paths."""

    def setUp(self):
        self.mock_root = MagicMock()
        # Baseline Tk scaling at 96 DPI: 96 / 72 = 1.3333333333333333
        self.mock_root.tk.call.return_value = '1.3333333333333333'
        self.mock_root.winfo_screenwidth.return_value = 1920
        self.mock_root.winfo_screenheight.return_value = 1080
        self.mock_root.winfo_x.return_value = -1
        self.mock_root.winfo_y.return_value = -1
        self.mock_root.winfo_width.return_value = 1
        self.mock_root.winfo_height.return_value = 1
        self.mock_root.winfo_pointerx.return_value = -1
        self.mock_root.winfo_pointery.return_value = -1

    def test_compute_mutter_ceiling_scale_half_integers_and_epsilon(self):
        """Verifies Mutter ceiling-derived integer scale across half-integers and epsilon boundaries."""
        # Baseline
        self.assertEqual(window_scaling.compute_mutter_ceiling_scale(1.0), 1)
        # Epsilon jitter: values within 1e-4 of integer do not trigger ceiling jump
        self.assertEqual(window_scaling.compute_mutter_ceiling_scale(1.00000001), 1)
        self.assertEqual(window_scaling.compute_mutter_ceiling_scale(1.00005), 1)
        # Values exceeding epsilon ceiling to 2
        self.assertEqual(window_scaling.compute_mutter_ceiling_scale(1.0002), 2)

        # Standard fractional values:
        self.assertEqual(window_scaling.compute_mutter_ceiling_scale(1.25), 2)
        self.assertEqual(window_scaling.compute_mutter_ceiling_scale(1.33333337), 2)
        self.assertEqual(window_scaling.compute_mutter_ceiling_scale(1.75), 2)
        self.assertEqual(window_scaling.compute_mutter_ceiling_scale(2.0), 2)
        self.assertEqual(window_scaling.compute_mutter_ceiling_scale(2.25), 3)

        # Boundaries immediately below, at, and above half-integers:
        self.assertEqual(window_scaling.compute_mutter_ceiling_scale(1.49), 2)
        self.assertEqual(window_scaling.compute_mutter_ceiling_scale(1.50), 2)
        self.assertEqual(window_scaling.compute_mutter_ceiling_scale(1.51), 2)
        self.assertEqual(window_scaling.compute_mutter_ceiling_scale(2.49), 3)
        self.assertEqual(window_scaling.compute_mutter_ceiling_scale(2.50), 3)
        self.assertEqual(window_scaling.compute_mutter_ceiling_scale(2.51), 3)

    def test_validate_inflation_scale_tolerance_boundaries(self):
        """Verifies explicit tolerance acceptance band and rejection of non-integer inflations."""
        # 1. Exact integers within tolerance
        self.assertEqual(window_scaling.validate_inflation_scale(1.25, 1.6), 2)
        self.assertEqual(window_scaling.validate_inflation_scale(1.0, 2.0), 2)
        self.assertEqual(window_scaling.validate_inflation_scale(1.33333337, 1.5), 2)

        # 2. Values within tolerance boundary (|deviation| <= 0.05)
        # 1.0 * 2.04 = 2.04 -> deviation 0.04 -> accepted as 2
        self.assertEqual(window_scaling.validate_inflation_scale(1.0, 2.04), 2)
        # 1.0 * 1.96 = 1.96 -> deviation 0.04 -> accepted as 2
        self.assertEqual(window_scaling.validate_inflation_scale(1.0, 1.96), 2)
        # 1.0 * 2.05 = 2.05 -> deviation 0.05 -> accepted as 2
        self.assertEqual(window_scaling.validate_inflation_scale(1.0, 2.05), 2)
        # 1.0 * 1.95 = 1.95 -> deviation 0.05 -> accepted as 2
        self.assertEqual(window_scaling.validate_inflation_scale(1.0, 1.95), 2)

        # 3. Values outside tolerance boundary (|deviation| > 0.05) -> rejected (returns None)
        # 1.0 * 2.06 = 2.06 -> deviation 0.06 -> rejected
        self.assertIsNone(window_scaling.validate_inflation_scale(1.0, 2.06))
        # 1.0 * 1.94 = 1.94 -> deviation 0.06 -> rejected
        self.assertIsNone(window_scaling.validate_inflation_scale(1.0, 1.94))

        # 4. Half-integers (deviation 0.50) -> rejected
        self.assertIsNone(window_scaling.validate_inflation_scale(1.0, 2.50))
        self.assertIsNone(window_scaling.validate_inflation_scale(1.0, 1.50))

    def test_compute_mutter_integer_scale_conservative_fallback_on_inconsistent_inflation(self):
        """When inflation deviates from an integer, falls back conservatively to ceiling scale."""
        # On scale 1.0, invalid 2.5 inflation falls back to ceiling 1 (does NOT round up to 3)
        self.assertEqual(window_scaling.compute_mutter_integer_scale(1.0, 2.5), 1)
        # On scale 1.25, invalid 2.5 inflation falls back to ceiling 2
        self.assertEqual(window_scaling.compute_mutter_integer_scale(1.25, 2.5), 2)

    def test_unreliable_xrandr_modes_skipped_when_mutter_modes_missing(self):
        """When Mutter reports neither current nor preferred mode, arbitrary XRandR modes are skipped."""
        mutter_data = {
            'serial': 12,
            'logical_monitors': [{'x': 0, 'y': 0, 'scale': 1.25, 'transform': 0, 'primary': True, 'connectors': ['VIRTUAL-1']}],
            'current_modes': {},
            'preferred_modes': {}
        }
        # XRandR returns multiple modes; the first mode is 3840x2160 (which would give false 0.8x inflation)
        xrandr_data = {
            'screen_w': 3072, 'screen_h': 1728,
            'monitors': {
                'VIRTUAL-1': {
                    'connector': 'VIRTUAL-1', 'primary': True, 'x': 0, 'y': 0, 'w': 3072, 'h': 1728,
                    'modes': [(3840, 2160), (2560, 1440), (1920, 1080), (1024, 768)]
                }
            }
        }
        # With Mutter modes missing, the code must skip VIRTUAL-1 inflation rather than picking 3840x2160,
        # and fall through to XRDB (which reports Xft.dpi: 192 -> 2.0x)
        with patch('sys.platform', 'linux'), \
             patch('window_scaling.get_mutter_display_state', return_value=mutter_data), \
             patch('window_scaling.get_xrandr_monitors', return_value=xrandr_data), \
             patch('window_scaling.get_xrdb_dpi', return_value=192.0):
            scale, diag = window_scaling.derive_effective_xwayland_scale(self.mock_root)
            self.assertEqual(scale, 2.0)
            self.assertEqual(diag['strategy'], 'xrdb_xft_dpi_fallback')

    def test_non_1080p_native_resolutions_no_hardcoded_assumptions(self):
        """Verifies scaling on non-1080p native monitors (e.g. 1440p and 4K) without guessing."""
        mutter_data = {
            'serial': 10,
            'logical_monitors': [{'x': 0, 'y': 0, 'scale': 1.25, 'transform': 0, 'primary': True, 'connectors': ['DP-1']}],
            'current_modes': {'DP-1': (2560, 1440)},
            'preferred_modes': {'DP-1': (2560, 1440)}
        }
        xrandr_data = {
            'screen_w': 4096, 'screen_h': 2304,
            'monitors': {'DP-1': {'connector': 'DP-1', 'primary': True, 'x': 0, 'y': 0, 'w': 4096, 'h': 2304, 'modes': [(2560, 1440)]}}
        }
        with patch('sys.platform', 'linux'), \
             patch('window_scaling.get_mutter_display_state', return_value=mutter_data), \
             patch('window_scaling.get_xrandr_monitors', return_value=xrandr_data):
            scale, diag = window_scaling.derive_effective_xwayland_scale(self.mock_root)
            self.assertEqual(scale, 2.0)
            dp_diag = diag['monitors']['DP-1']
            self.assertEqual(dp_diag['native_width'], 2560)
            self.assertAlmostEqual(dp_diag['inflation_ratio'], 1.6, places=2)

    def test_standard_96_dpi_fallback_behavior(self):
        """Standard 96 DPI returns scale_ratio 1.0 and exact baseline geometry when Mutter is absent."""
        with patch('sys.platform', 'linux'), \
             patch('window_scaling.get_mutter_display_state', return_value=None), \
             patch('window_scaling.get_xrandr_monitors', return_value=None), \
             patch('window_scaling.get_xrdb_dpi', return_value=None):
            ratio = window_scaling.get_display_scale_ratio(self.mock_root)
            self.assertEqual(ratio, 1.0)
            geom, min_size, diag = window_scaling.calculate_window_geometry(self.mock_root)
            self.assertEqual(geom, '1140x740')
            self.assertEqual(min_size, (980, 680))
            self.assertEqual(diag['scale_ratio'], 1.0)

    def test_gnome_100_percent_session_scale(self):
        """At 100% GNOME scale, derives 1.0x session scale and 1140x740 baseline."""
        mutter_data = {
            'serial': 1,
            'logical_monitors': [{'x': 0, 'y': 0, 'scale': 1.0, 'transform': 0, 'primary': True, 'connectors': ['eDP-1']}],
            'current_modes': {'eDP-1': (1920, 1080)},
            'preferred_modes': {'eDP-1': (1920, 1080)}
        }
        xrandr_data = {
            'screen_w': 1920, 'screen_h': 1080,
            'monitors': {'eDP-1': {'connector': 'eDP-1', 'primary': True, 'x': 0, 'y': 0, 'w': 1920, 'h': 1080, 'modes': [(1920, 1080)]}}
        }
        with patch('sys.platform', 'linux'), \
             patch('window_scaling.get_mutter_display_state', return_value=mutter_data), \
             patch('window_scaling.get_xrandr_monitors', return_value=xrandr_data):
            ratio = window_scaling.get_display_scale_ratio(self.mock_root)
            self.assertEqual(ratio, 1.0)
            geom, min_size, diag = window_scaling.calculate_window_geometry(self.mock_root)
            self.assertEqual(geom, '1140x740')
            self.assertEqual(min_size, (980, 680))
            self.assertEqual(diag['strategy'], 'gnome_mutter_xrandr_session')
            self.assertEqual(diag['effective_scale'], 1.0)

    def test_gnome_125_percent_session_scale(self):
        """At 125% GNOME scale, derives 2.0x integer scale and 2280x1480 geometry without double scaling."""
        mutter_data = {
            'serial': 2,
            'logical_monitors': [{'x': 0, 'y': 0, 'scale': 1.25, 'transform': 0, 'primary': True, 'connectors': ['eDP-1']}],
            'current_modes': {'eDP-1': (1920, 1080)},
            'preferred_modes': {'eDP-1': (1920, 1080)}
        }
        xrandr_data = {
            'screen_w': 3072, 'screen_h': 1728,
            'monitors': {'eDP-1': {'connector': 'eDP-1', 'primary': True, 'x': 0, 'y': 0, 'w': 3072, 'h': 1728, 'modes': [(1920, 1080)]}}
        }
        self.mock_root.winfo_screenwidth.return_value = 3072
        self.mock_root.winfo_screenheight.return_value = 1728

        with patch('sys.platform', 'linux'), \
             patch('window_scaling.get_mutter_display_state', return_value=mutter_data), \
             patch('window_scaling.get_xrandr_monitors', return_value=xrandr_data):
            ratio = window_scaling.get_display_scale_ratio(self.mock_root)
            self.assertEqual(ratio, 2.0)
            geom, min_size, diag = window_scaling.calculate_window_geometry(self.mock_root)
            self.assertEqual(geom, '2280x1480')
            self.assertEqual(min_size, (1960, 1360))
            self.assertEqual(diag['strategy'], 'gnome_mutter_xrandr_session')
            self.assertEqual(diag['effective_scale'], 2.0)
            self.mock_root.tk.call.assert_any_call('tk', 'scaling', window_scaling.BASELINE_TK_SCALING * 2.0)

    def test_mixed_monitor_session_wide_scaling(self):
        """In mixed 100%/125% sessions, both monitor positions return the same session-wide 2x scale."""
        mutter_data = {
            'serial': 3,
            'logical_monitors': [
                {'x': 0, 'y': 0, 'scale': 1.0, 'transform': 0, 'primary': False, 'connectors': ['HDMI-1']},
                {'x': 0, 'y': 1080, 'scale': 1.25, 'transform': 0, 'primary': True, 'connectors': ['eDP-1']},
            ],
            'current_modes': {'HDMI-1': (1920, 1080), 'eDP-1': (1920, 1080)},
            'preferred_modes': {'HDMI-1': (1920, 1080), 'eDP-1': (1920, 1080)}
        }
        xrandr_data = {
            'screen_w': 3840, 'screen_h': 3888,
            'monitors': {
                'HDMI-1': {'connector': 'HDMI-1', 'primary': False, 'x': 0, 'y': 0, 'w': 3840, 'h': 2160, 'modes': [(1920, 1080)]},
                'eDP-1': {'connector': 'eDP-1', 'primary': True, 'x': 0, 'y': 2160, 'w': 3072, 'h': 1728, 'modes': [(1920, 1080)]},
            }
        }
        with patch('sys.platform', 'linux'), \
             patch('window_scaling.get_mutter_display_state', return_value=mutter_data), \
             patch('window_scaling.get_xrandr_monitors', return_value=xrandr_data):
            self.mock_root.winfo_x.return_value = 100
            self.mock_root.winfo_y.return_value = 200
            scale_hdmi, diag_hdmi = window_scaling.derive_effective_xwayland_scale(self.mock_root)
            self.assertEqual(scale_hdmi, 2.0)

            self.mock_root.winfo_x.return_value = 100
            self.mock_root.winfo_y.return_value = 2500
            scale_edp, diag_edp = window_scaling.derive_effective_xwayland_scale(self.mock_root)
            self.assertEqual(scale_edp, 2.0)
            self.assertEqual(scale_hdmi, scale_edp)

    def test_current_mode_prioritized_over_preferred_mode(self):
        """Current physical mode is prioritized over preferred EDID mode when computing inflation."""
        mutter_data = {
            'serial': 4,
            'logical_monitors': [{
                'x': 0, 'y': 0, 'scale': 1.0, 'transform': 0, 'primary': True,
                'connectors': ['DP-1']
            }],
            'current_modes': {'DP-1': (1920, 1080)},
            'preferred_modes': {'DP-1': (3840, 2160)}
        }
        xrandr_data = {
            'screen_w': 1920, 'screen_h': 1080,
            'monitors': {
                'DP-1': {'connector': 'DP-1', 'primary': True, 'x': 0, 'y': 0, 'w': 1920, 'h': 1080, 'modes': [(3840, 2160), (1920, 1080)]}
            }
        }
        with patch('sys.platform', 'linux'), \
             patch('window_scaling.get_mutter_display_state', return_value=mutter_data), \
             patch('window_scaling.get_xrandr_monitors', return_value=xrandr_data):
            scale, diag = window_scaling.derive_effective_xwayland_scale(self.mock_root)
            self.assertEqual(scale, 1.0)
            dp_diag = diag['monitors']['DP-1']
            self.assertEqual(dp_diag['native_width'], 1920)
            self.assertEqual(dp_diag['inflation_ratio'], 1.0)

    def test_dbus_failure_fallback_to_xrdb(self):
        """When D-Bus query fails, falls back cleanly to XRDB Xft.dpi with logged warning."""
        with patch('sys.platform', 'linux'), \
             patch('window_scaling.get_mutter_display_state', return_value=None), \
             patch('window_scaling.get_xrdb_dpi', return_value=192.0):
            scale, diag = window_scaling.derive_effective_xwayland_scale(self.mock_root)
            self.assertEqual(scale, 2.0)
            self.assertEqual(diag['strategy'], 'xrdb_xft_dpi_fallback')
            self.assertEqual(diag['xrdb_dpi'], 192.0)

    def test_xrandr_and_dbus_failure_fallback_to_tk(self):
        """When D-Bus and XRandR and XRDB fail, falls back to Tk calibrated scaling."""
        self.mock_root.tk.call.return_value = '2.6666666666666665'
        with patch('sys.platform', 'linux'), \
             patch('window_scaling.get_mutter_display_state', return_value=None), \
             patch('window_scaling.get_xrandr_monitors', return_value=None), \
             patch('window_scaling.get_xrdb_dpi', return_value=None):
            scale, diag = window_scaling.derive_effective_xwayland_scale(self.mock_root)
            self.assertEqual(scale, 2.0)
            self.assertEqual(diag['strategy'], 'tk_calibrated_scaling_fallback')

    def test_all_subsystems_failure_fallback_to_default_baseline(self):
        """When all detection layers fail or throw exceptions, returns safe 1.0 baseline."""
        self.mock_root.tk.call.side_effect = RuntimeError("Tk unavailable")
        with patch('sys.platform', 'linux'), \
             patch('window_scaling.get_mutter_display_state', side_effect=RuntimeError("D-Bus down")), \
             patch('window_scaling.get_xrandr_monitors', side_effect=RuntimeError("XRandR missing")), \
             patch('window_scaling.get_xrdb_dpi', side_effect=RuntimeError("XRDB failed")):
            scale, diag = window_scaling.derive_effective_xwayland_scale(self.mock_root)
            self.assertEqual(scale, 1.0)
            self.assertEqual(diag['strategy'], 'default_baseline_fallback')

    def test_screen_smaller_than_preferred_window(self):
        """When screen dimensions are smaller than preferred window, clamp to viewport."""
        self.mock_root.winfo_screenwidth.return_value = 1024
        self.mock_root.winfo_screenheight.return_value = 768
        with patch('sys.platform', 'linux'), \
             patch('window_scaling.get_mutter_display_state', return_value=None), \
             patch('window_scaling.get_xrandr_monitors', return_value=None), \
             patch('window_scaling.get_xrdb_dpi', return_value=None):
            geom, min_size, diag = window_scaling.calculate_window_geometry(self.mock_root)
            self.assertTrue(diag['strategy'].endswith('_clamped_to_screen'))
            w, h = map(int, geom.split('x'))
            self.assertLessEqual(w, 1024)
            self.assertLessEqual(h, 768)
            self.assertLessEqual(min_size[0], 1024)
            self.assertLessEqual(min_size[1], 768)

    def test_tiny_screen_clamp_minimum_size(self):
        """On tiny screens (e.g. 800x600), minimum dimensions never exceed screen bounds."""
        self.mock_root.winfo_screenwidth.return_value = 800
        self.mock_root.winfo_screenheight.return_value = 600
        with patch('sys.platform', 'linux'), \
             patch('window_scaling.get_mutter_display_state', return_value=None), \
             patch('window_scaling.get_xrandr_monitors', return_value=None), \
             patch('window_scaling.get_xrdb_dpi', return_value=None):
            geom, min_size, diag = window_scaling.calculate_window_geometry(self.mock_root)
            w, h = map(int, geom.split('x'))
            self.assertLessEqual(w, 800)
            self.assertLessEqual(h, 600)
            self.assertLessEqual(min_size[0], 800)
            self.assertLessEqual(min_size[1], 600)

    def test_high_dpi_small_screen_clamping(self):
        """At 2x scale on 1920x1080 display, scaled 2280x1480 is clamped without exceeding screen."""
        self.mock_root.winfo_screenwidth.return_value = 1920
        self.mock_root.winfo_screenheight.return_value = 1080
        with patch('sys.platform', 'linux'), \
             patch('window_scaling.derive_effective_xwayland_scale', return_value=(2.0, {'strategy': 'gnome_test'})):
            geom, min_size, diag = window_scaling.calculate_window_geometry(self.mock_root)
            w, h = map(int, geom.split('x'))
            self.assertLessEqual(w, 1920)
            self.assertLessEqual(h, 1080)
            self.assertLessEqual(min_size[0], 1920)
            self.assertLessEqual(min_size[1], 1080)
            self.assertTrue(diag['strategy'].endswith('_clamped_to_screen'))

    def test_windows_geometry_remains_unchanged(self):
        """On Windows, calculate_window_geometry preserves baseline and NEVER touches Tk scaling."""
        self.mock_root.tk.call.return_value = '2.6666666666666665'
        self.mock_root.winfo_screenwidth.return_value = 800
        self.mock_root.winfo_screenheight.return_value = 600
        with patch('sys.platform', 'win32'):
            geom, min_size, diag = window_scaling.calculate_window_geometry(self.mock_root)
            self.assertEqual(geom, '1140x740')
            self.assertEqual(min_size, (980, 680))
            self.assertEqual(diag['strategy'], 'windows_native_baseline')
            self.assertEqual(diag['scale_ratio'], 1.0)
            for call in self.mock_root.tk.call.mock_calls:
                self.assertNotIn(('tk', 'scaling'), call.args)

    def test_no_double_scaling_repeated_calls(self):
        """Scale ratio is calculated once and repeated calls do not compound scaling."""
        with patch('sys.platform', 'linux'), \
             patch('window_scaling.get_mutter_display_state', return_value=None), \
             patch('window_scaling.get_xrandr_monitors', return_value=None), \
             patch('window_scaling.get_xrdb_dpi', return_value=None):
            ratio1 = window_scaling.get_display_scale_ratio(self.mock_root)
            ratio2 = window_scaling.get_display_scale_ratio(self.mock_root)
            self.assertEqual(ratio1, ratio2)
            self.assertEqual(ratio1, 1.0)
