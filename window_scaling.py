"""Window geometry calculation, display metric detection, and DPI scaling helpers.

Distinguishes Tk scaling from compositor scaling, avoids double-scaling,
preserves the 1140x740 logical baseline, and adapts initial geometry to
available screen real estate.

Note on Desktop Scaling Changes:
    Under XWayland on Linux, Mutter sets the X11 virtual screen resolution and
    publishes Xft.dpi (e.g., 96 or 192) at session startup or when display
    settings change. However, Tk 8.6 and libXft cache font rendering DPI upon
    process initialization and do not automatically re-scale existing widgets
    in response to dynamic X11 screen change notifications.
    Consequently, changing GNOME desktop scaling settings requires restarting
    the application for the new scale factor and font metrics to take effect.
"""
import logging
import math
import re
import subprocess
import sys
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

BASELINE_DPI = 96.0
BASELINE_TK_SCALING = BASELINE_DPI / 72.0  # 1.3333333333333333
BASELINE_WIDTH = 1140
BASELINE_HEIGHT = 740
BASELINE_MIN_WIDTH = 980
BASELINE_MIN_HEIGHT = 680

# Tolerance for accepting inflation-derived integer scales.
# Discrete panel pixel discretization on panels >= 800px causes deviations |delta| <= 0.005.
# A tolerance of 0.05 accommodates discrete pixel rounding across odd panel dimensions
# (e.g. 1366x768) and IEEE 754 precision noise while strictly rejecting non-integer inflations
# (such as half-integers 2.5 or third-integers).
INFLATION_INTEGER_TOLERANCE = 0.05


def compute_mutter_ceiling_scale(mutter_scale: float) -> int:
    """Compute Mutter's baseline compositor integer scale using a ceiling operation.

    Under GNOME Mutter, XWayland fractional scaling allocates an integer surface buffer:
        S_ceil = ceil(mutter_scale)
    An epsilon of 1e-4 prevents floating-point precision noise (e.g. 1.0000001) from
    erroneously bumping the integer scale.
    """
    if mutter_scale <= 1.0:
        return 1
    return max(1, int(math.ceil(mutter_scale - 1e-4)))


def validate_inflation_scale(
    mutter_scale: float,
    inflation_ratio: float,
    tolerance: float = INFLATION_INTEGER_TOLERANCE,
) -> Optional[int]:
    """Validate and derive integer scale from XRandR inflation ratio.

    Analytically, Mutter's XWayland canvas inflation satisfies:
        inflation_ratio * mutter_scale = S_session (exact integer)
    Subject only to discrete panel pixel discretization noise (|delta| <= 0.005).

    Returns:
        int scale if product is within tolerance of an integer;
        None if the measurement is inconsistent (outside tolerance).
    """
    if inflation_ratio <= 1.05 and mutter_scale <= 1.0:
        return 1

    raw_product = inflation_ratio * mutter_scale
    nearest_int = int(math.floor(raw_product + 0.5))
    deviation = abs(raw_product - nearest_int)

    if deviation <= tolerance + 1e-9:
        return max(1, nearest_int)

    logger.warning(
        "Inflation product %s (inflation %s * scale %s) deviates from integer %s by %s (tolerance %s); rejecting measurement.",
        raw_product, inflation_ratio, mutter_scale, nearest_int, deviation, tolerance
    )
    return None


def compute_mutter_integer_scale(
    mutter_scale: float,
    inflation_ratio: float = 1.0,
    tolerance: float = INFLATION_INTEGER_TOLERANCE,
) -> int:
    """Determine effective monitor scale combining Mutter ceiling and validated inflation.

    1. Computes Mutter's ceiling-derived integer scale:
           S_ceil = compute_mutter_ceiling_scale(mutter_scale)
    2. If inflation_ratio > 1.05 (XRandR canvas supersampling is active):
           S_infl = validate_inflation_scale(mutter_scale, inflation_ratio, tolerance)
       - If S_infl is valid (within tolerance of an integer):
             return max(S_ceil, S_infl)
       - If S_infl is invalid (outside tolerance):
             Logs the inconsistency and uses conservative fallback S_ceil.
    3. Otherwise:
           return S_ceil.
    """
    s_ceil = compute_mutter_ceiling_scale(mutter_scale)

    if inflation_ratio > 1.05:
        s_infl = validate_inflation_scale(mutter_scale, inflation_ratio, tolerance)
        if s_infl is not None:
            return max(s_ceil, s_infl)
        logger.info(
            "Using conservative ceiling scale %s due to unvalidated inflation %s on scale %s",
            s_ceil, inflation_ratio, mutter_scale
        )
        return s_ceil

    return s_ceil


def get_mutter_display_state() -> Optional[Dict[str, Any]]:
    """Query GNOME Mutter DisplayConfig via session D-Bus.

    Returns a dict containing logical_monitors, current_modes, and preferred_modes,
    or None if D-Bus / Mutter is unavailable.
    """
    try:
        import dbus
        bus = dbus.SessionBus()
        obj = bus.get_object('org.gnome.Mutter.DisplayConfig', '/org/gnome/Mutter/DisplayConfig')
        iface = dbus.Interface(obj, 'org.gnome.Mutter.DisplayConfig')
        serial, monitors, logical_monitors, properties = iface.GetCurrentState()

        parsed_lm = []
        for lm in logical_monitors:
            x, y, scale, transform, primary, mon_list, props = lm
            parsed_lm.append({
                'x': int(x),
                'y': int(y),
                'scale': float(scale),
                'transform': int(transform),
                'primary': bool(primary),
                'connectors': [str(m[0]) for m in mon_list],
            })

        current_modes = {}
        preferred_modes = {}
        for mon in monitors:
            conn_name = str(mon[0][0])
            for mode in mon[1]:
                mode_props = mode[6]
                if mode_props.get('is-current', False):
                    current_modes[conn_name] = (int(mode[1]), int(mode[2]))
                if mode_props.get('is-preferred', False):
                    preferred_modes[conn_name] = (int(mode[1]), int(mode[2]))

        return {
            'serial': int(serial),
            'logical_monitors': parsed_lm,
            'current_modes': current_modes,
            'preferred_modes': preferred_modes,
        }
    except Exception as e:
        logger.debug("Mutter DisplayConfig D-Bus query unavailable: %s", e)
        return None


def get_xrandr_monitors() -> Optional[Dict[str, Any]]:
    """Query xrandr for connected outputs, current modes, and bounding boxes.

    Returns a dict with 'screen_w', 'screen_h', and 'monitors' dict mapping
    connector name to output details, or None if xrandr is unavailable.
    """
    try:
        res = subprocess.run(
            ['xrandr', '--current'], capture_output=True, text=True, timeout=2.0
        )
        if res.returncode != 0:
            return None

        monitors = {}
        screen_w, screen_h = 0, 0
        current_mon = None

        for line in res.stdout.splitlines():
            if line.startswith('Screen 0:'):
                m = re.search(r'current\s+(\d+)\s+x\s+(\d+)', line)
                if m:
                    screen_w, screen_h = int(m.group(1)), int(m.group(2))
                continue

            conn_match = re.match(
                r'^([A-Za-z0-9-]+)\s+connected\s+(?:primary\s+)?(\d+)x(\d+)\+(\d+)\+(\d+)',
                line,
            )
            if conn_match:
                name = conn_match.group(1)
                monitors[name] = {
                    'connector': name,
                    'primary': 'primary' in line,
                    'x': int(conn_match.group(4)),
                    'y': int(conn_match.group(5)),
                    'w': int(conn_match.group(2)),
                    'h': int(conn_match.group(3)),
                    'modes': [],
                }
                current_mon = name
            elif current_mon and re.match(r'^\s+(\d+)x(\d+)', line):
                mode_match = re.match(r'^\s+(\d+)x(\d+)', line)
                if mode_match:
                    monitors[current_mon]['modes'].append(
                        (int(mode_match.group(1)), int(mode_match.group(2)))
                    )

        if not monitors:
            return None
        return {'screen_w': screen_w, 'screen_h': screen_h, 'monitors': monitors}
    except Exception as e:
        logger.debug("XRandR query unavailable: %s", e)
        return None


def get_xrdb_dpi() -> Optional[float]:
    """Query xrdb for Xft.dpi.

    Returns float DPI (e.g. 96.0, 192.0) or None if unavailable.
    """
    try:
        res = subprocess.run(['xrdb', '-query'], capture_output=True, text=True, timeout=2.0)
        if res.returncode == 0:
            m = re.search(r'Xft\.dpi:\s*(\d+(?:\.\d+)?)', res.stdout)
            if m:
                return float(m.group(1))
    except Exception:
        pass
    return None


def derive_effective_xwayland_scale(root=None) -> Tuple[float, Dict[str, Any]]:
    """Determine the session-wide effective integer scale for XWayland window geometry and rendering.

    Under XWayland with GNOME Mutter, XWayland operates as a unified root canvas scaled
    to the maximum integer scale required by any connected monitor:
        S_session = max_{monitors} compute_mutter_integer_scale(mutter_scale, inflation)

    In mixed 100%/125% configurations, Mutter renders the XWayland buffer at 2x across
    the entire session and downsamples per display (2.0x on 100% monitor, 1.6x on 125% monitor).
    Therefore, a consistent session-wide 2x scale applies regardless of which monitor contains
    the window.

    Native resolution detection:
    - Uses Mutter's current_modes first.
    - Uses Mutter's preferred_modes only when the current mode is unavailable.
    - If neither is available, does NOT pick an arbitrary mode from XRandR; skips
      inflation calculation for that connector and falls back to secondary strategies.

    For non-GNOME compositors (or if D-Bus is unavailable), safely falls back to XRDB Xft.dpi,
    calibrated Tk scaling, or baseline 1.0 without guessing physical panel resolutions.

    Returns:
        (effective_scale, diagnostic_metadata)
    """
    if sys.platform == 'win32':
        return 1.0, {
            'platform': 'win32',
            'strategy': 'windows_native_baseline',
            'scale_ratio': 1.0,
        }

    try:
        mutter_state = get_mutter_display_state()
    except Exception as e:
        logger.debug("Failed getting Mutter state: %s", e)
        mutter_state = None

    try:
        xrandr_state = get_xrandr_monitors()
    except Exception as e:
        logger.debug("Failed getting XRandR state: %s", e)
        xrandr_state = None

    # Strategy 1: GNOME Mutter + XRandR session-wide scale derivation
    if mutter_state and xrandr_state:
        try:
            logical_mons = mutter_state.get('logical_monitors', [])
            current_modes = mutter_state.get('current_modes', {})
            pref_modes = mutter_state.get('preferred_modes', {})
            xrandr_mons = xrandr_state.get('monitors', {})

            derived_scales = []
            monitor_details = {}

            for lm in logical_mons:
                mutter_scale = float(lm.get('scale', 1.0))
                for conn in lm.get('connectors', []):
                    xmon = xrandr_mons.get(conn)
                    if not xmon:
                        continue
                    cur_w = xmon['w']

                    # Prioritize is-current physical mode; fall back to is-preferred.
                    # If neither is reported by Mutter, do NOT select an arbitrary mode from XRandR.
                    native_mode = current_modes.get(conn) or pref_modes.get(conn)
                    if not native_mode:
                        logger.info(
                            "No physical resolution reported by Mutter for connector %s; skipping inflation calculation.",
                            conn,
                        )
                        continue

                    native_w = native_mode[0]
                    inflation = cur_w / native_w if native_w > 0 else 1.0
                    m_scale = float(compute_mutter_integer_scale(mutter_scale, inflation))

                    derived_scales.append(m_scale)
                    monitor_details[conn] = {
                        'mutter_scale': mutter_scale,
                        'current_width': cur_w,
                        'native_width': native_w,
                        'inflation_ratio': inflation,
                        'derived_scale': m_scale,
                    }

            if derived_scales:
                session_scale = max(derived_scales)
                return session_scale, {
                    'platform': sys.platform,
                    'strategy': 'gnome_mutter_xrandr_session',
                    'effective_scale': session_scale,
                    'monitors': monitor_details,
                }
            else:
                logger.warning(
                    "No physical modes could be reliably established via Mutter; falling back to secondary detection."
                )
        except Exception as e:
            logger.debug("Error during dynamic session scaling detection: %s", e)

    # Strategy 2: XRDB Xft.dpi fallback (standalone X11 or non-Mutter compositors)
    try:
        xrdb_dpi = get_xrdb_dpi()
    except Exception as e:
        logger.debug("Failed getting XRDB DPI: %s", e)
        xrdb_dpi = None

    if xrdb_dpi and xrdb_dpi > 0:
        ratio = xrdb_dpi / BASELINE_DPI
        eff_scale = max(1.0, float(math.floor(ratio + 0.5)))
        logger.info("Using XRDB Xft.dpi fallback: %s DPI (scale %sx)", xrdb_dpi, eff_scale)
        return eff_scale, {
            'platform': sys.platform,
            'strategy': 'xrdb_xft_dpi_fallback',
            'xrdb_dpi': xrdb_dpi,
            'effective_scale': eff_scale,
        }

    # Strategy 3: Tk calibrated scaling fallback
    if root is not None:
        try:
            tk_scaling = float(root.tk.call('tk', 'scaling'))
            if tk_scaling > 0:
                ratio = tk_scaling / BASELINE_TK_SCALING
                if not (0.95 <= ratio <= 1.05):
                    eff_scale = max(1.0, float(math.floor(ratio + 0.5)))
                    logger.info("Using Tk calibrated scaling fallback: %s (scale %sx)", tk_scaling, eff_scale)
                    return eff_scale, {
                        'platform': sys.platform,
                        'strategy': 'tk_calibrated_scaling_fallback',
                        'tk_scaling': tk_scaling,
                        'effective_scale': eff_scale,
                    }
        except Exception as e:
            logger.debug("Failed reading Tk scaling: %s", e)

    # Strategy 4: Default safe baseline
    logger.info("Falling back to default 1.0 display scaling baseline.")
    return 1.0, {
        'platform': sys.platform,
        'strategy': 'default_baseline_fallback',
        'effective_scale': 1.0,
    }


def get_display_scale_ratio(root=None) -> float:
    """Return the display scaling ratio relative to the standard 96 DPI baseline."""
    eff_scale, _ = derive_effective_xwayland_scale(root)
    return eff_scale


def calculate_window_geometry(
    root,
    base_w: int = BASELINE_WIDTH,
    base_h: int = BASELINE_HEIGHT,
    min_w: int = BASELINE_MIN_WIDTH,
    min_h: int = BASELINE_MIN_HEIGHT,
) -> Tuple[str, Tuple[int, int], Dict[str, Any]]:
    """Compute initial window geometry, minimum size, and configure Tk scaling.

    Preserves exact baseline coordinates on Windows. On Linux/XWayland, scales
    window geometry proportionally to the measured session-wide scale and configures
    Tk scaling to match Xft.dpi without double scaling.

    Returns:
        (geometry_string, (min_width, min_height), diagnostics_dict)
    """
    if sys.platform == 'win32':
        diag = {
            'platform': 'win32',
            'strategy': 'windows_native_baseline',
            'scale_ratio': 1.0,
            'geometry': f'{base_w}x{base_h}',
            'minsize': (min_w, min_h),
        }
        return f'{base_w}x{base_h}', (min_w, min_h), diag

    # Linux / XWayland
    scale_ratio, diag = derive_effective_xwayland_scale(root)

    try:
        tk_scale_val = BASELINE_TK_SCALING * scale_ratio
        root.tk.call('tk', 'scaling', tk_scale_val)
    except Exception as e:
        logger.debug("Could not set tk scaling: %s", e)

    scaled_w = int(round(base_w * scale_ratio))
    scaled_h = int(round(base_h * scale_ratio))
    scaled_min_w = int(round(min_w * scale_ratio))
    scaled_min_h = int(round(min_h * scale_ratio))

    try:
        screen_w = int(root.winfo_screenwidth())
        screen_h = int(root.winfo_screenheight())
    except Exception:
        screen_w, screen_h = 0, 0

    strategy = diag.get('strategy', 'gnome_mutter_xrandr_session')
    if screen_w > 0 and screen_h > 0:
        max_allowed_w = min(screen_w, max(min_w, int(screen_w * 0.95)))
        max_allowed_h = min(screen_h, max(min_h, int(screen_h * 0.90)))

        if scaled_w > max_allowed_w or scaled_h > max_allowed_h:
            scaled_w = min(scaled_w, max_allowed_w)
            scaled_h = min(scaled_h, max_allowed_h)
            strategy += '_clamped_to_screen'

        scaled_min_w = min(scaled_min_w, scaled_w, screen_w)
        scaled_min_h = min(scaled_min_h, scaled_h, screen_h)

    geometry_str = f'{scaled_w}x{scaled_h}'
    min_size = (scaled_min_w, scaled_min_h)

    diagnostics = {
        **diag,
        'scale_ratio': scale_ratio,
        'strategy': strategy,
        'screen': (screen_w, screen_h),
        'geometry': geometry_str,
        'minsize': min_size,
    }
    return geometry_str, min_size, diagnostics
