"""Shared design tokens and typography for cross-platform desktop UI consistency.

Maintains Windows visual reference values as the canonical baseline while
providing unified typography scales, padding, and spacing definitions
independent of host platform.
"""
import ctypes
from pathlib import Path
import sys


def load_bundled_font(font_path: Path) -> bool:
    """Register a private TTF/OTF font file for the current process without system installation."""
    if not font_path.is_file():
        return False
    if sys.platform == 'win32':
        # FR_PRIVATE = 0x10
        try:
            return bool(ctypes.windll.gdi32.AddFontResourceExW(str(font_path), 0x10, 0))
        except Exception:
            return False
    elif sys.platform.startswith('linux'):
        try:
            libfc = ctypes.CDLL('libfontconfig.so.1')
            libfc.FcInit()
            libfc.FcConfigAppFontAddFile.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
            libfc.FcConfigAppFontAddFile.restype = ctypes.c_bool
            return bool(libfc.FcConfigAppFontAddFile(None, str(font_path).encode('utf-8')))
        except Exception:
            return False
    return False


def resolve_font_family() -> str:
    """Select the primary font family.

    Windows uses Segoe UI by default. Linux prefers bundled Inter or installed
    Segoe UI, gracefully falling back to standard system sans-serif fonts.
    """
    if sys.platform == 'win32':
        return 'Segoe UI'

    # Check for bundled Inter fonts in assets or tools
    font_candidates = [
        Path(__file__).resolve().parent / 'runtime_assets' / 'fonts' / 'Inter-Regular.otf',
        Path(__file__).resolve().parent / 'runtime_assets' / 'fonts' / 'Inter-Regular.ttf',
        Path(__file__).resolve().parent / 'tools' / 'fonts' / 'Inter-Regular.otf',
        Path(__file__).resolve().parent / 'tools' / 'fonts' / 'Inter-Regular.ttf',
    ]
    for candidate in font_candidates:
        if candidate.is_file() and load_bundled_font(candidate):
            bold_candidate = candidate.with_name('Inter-Bold' + candidate.suffix)
            if bold_candidate.is_file():
                load_bundled_font(bold_candidate)
            return 'Inter'

    # Check if Fontconfig has Segoe UI or Inter available
    try:
        libfc = ctypes.CDLL('libfontconfig.so.1')
        libfc.FcInit()
        libfc.FcNameParse.argtypes = [ctypes.c_char_p]
        libfc.FcNameParse.restype = ctypes.c_void_p
        libfc.FcConfigSubstitute.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int]
        libfc.FcDefaultSubstitute.argtypes = [ctypes.c_void_p]
        libfc.FcFontMatch.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        libfc.FcFontMatch.restype = ctypes.c_void_p
        libfc.FcPatternGetString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int, ctypes.POINTER(ctypes.c_char_p)]
        libfc.FcPatternGetString.restype = ctypes.c_int

        for family in (b'Segoe UI', b'Inter'):
            pattern = libfc.FcNameParse(family)
            if pattern:
                libfc.FcConfigSubstitute(None, pattern, 0)
                libfc.FcDefaultSubstitute(pattern)
                res = ctypes.c_int()
                match = libfc.FcFontMatch(None, pattern, ctypes.byref(res))
                if match:
                    family_out = ctypes.c_char_p()
                    if libfc.FcPatternGetString(match, b'family', 0, ctypes.byref(family_out)) == 0:
                        matched_name = family_out.value.decode('utf-8', errors='ignore')
                        if matched_name.lower() == family.decode('utf-8').lower():
                            return family.decode('utf-8')
    except Exception:
        pass

    return 'Segoe UI'


# Canonical font family for UI elements
FONT_FAMILY = resolve_font_family()

# --- Typography Hierarchy (Canonical Windows Baseline) ---
FONT_DISPLAY = (FONT_FAMILY, 24, 'bold')          # Rail Header: 'JAR\nREVIVAL'
FONT_TITLE_LG = (FONT_FAMILY, 23, 'bold')         # Main Header: 'Your collection'
FONT_TITLE_MD = (FONT_FAMILY, 20, 'bold')         # Detail Title: selected game name
FONT_COVER_PREVIEW = (FONT_FAMILY, 28, 'bold')    # Cover Placeholder: 'JAR'
FONT_BUTTON_ACCENT = (FONT_FAMILY, 11, 'bold')    # Accent buttons ('+ Add game', 'Play')
FONT_TREEVIEW = (FONT_FAMILY, 11)                 # Treeview rows
FONT_SECTION_HEADER = (FONT_FAMILY, 10, 'bold')   # Rail Section: '  ◉  Your library'
FONT_TAB_BUTTON = (FONT_FAMILY, 10, 'bold')       # Detail TabNavigation buttons
FONT_BODY = (FONT_FAMILY, 10)                     # Search entry, global body, cache info
FONT_BODY_BOLD = (FONT_FAMILY, 10, 'bold')        # Bold body items
FONT_BODY_MUTED = (FONT_FAMILY, 9)                # Subtitles, telemetry, compatibility info
FONT_BADGE = (FONT_FAMILY, 9, 'bold')             # Badges ('SAVED & READY')
FONT_TABLE_HEADING = (FONT_FAMILY, 9, 'bold')     # Treeview headings
FONT_CAPTION = (FONT_FAMILY, 8)                   # Footers, instructions, helper text
FONT_CAPTION_BOLD = (FONT_FAMILY, 8, 'bold')      # Card subheadings ('SEARCH YOUR GAMES', etc.)

# --- Spacing & Padding Tokens (Canonical Windows Baseline) ---
# Rail sidebar
PAD_RAIL_X = 20
PAD_RAIL_Y = 26
PAD_RAIL_SUBTITLE_Y = (8, 32)
PAD_RAIL_SECTION_PADX = 8
PAD_RAIL_SECTION_PADY = 12
PAD_RAIL_DEMO_Y = (12, 0)

# Main container & headers
PAD_MAIN_X = 20
PAD_MAIN_Y = 22
PAD_HEADER_Y = (0, 20)
PAD_HEADER_SUBTITLE_Y = (4, 0)

# Detail pane & cards
PAD_DETAIL_X = 20
PAD_DETAIL_Y = 16
PAD_DETAIL_SUBTITLE_Y = (2, 12)
PAD_COVER_X = 14
PAD_COVER_Y = 12
PAD_PREVIEW_RIGHT_X = (0, 12)
PAD_CACHE_INFO_Y = (5, 4)
PAD_VIEW_CONTENT_PADX = 4
PAD_VIEW_CONTENT_PADY = 10
PAD_TAB_NAV_Y = (16, 8)
PAD_TAB_BUTTON_PADX = 4
PAD_TAB_BUTTON_PADY = 6

# Footer
PAD_FOOTER_Y = (10, 0)
PAD_FOOTER_BG_Y = (0, 6)
PAD_PROGRESS_Y = (8, 10)

# --- Dimensions ---
WIDTH_RAIL = 168
BASE_WINDOW_WIDTH = 1140
BASE_WINDOW_HEIGHT = 740
MIN_WINDOW_WIDTH = 980
MIN_WINDOW_HEIGHT = 680
ROW_HEIGHT_TREEVIEW = 54
WIDTH_TREEVIEW_ACTIONS = 84
WIDTH_TREEVIEW_INITIAL_TITLE = 165

# --- Color Palette ---
COLOR_BG = '#0c121c'
COLOR_PANEL = '#121c29'
COLOR_CARD = '#192636'
COLOR_CARD_HOVER = '#263649'
COLOR_CARD_ACTIVE = '#354b60'

COLOR_ACCENT = '#84e4c7'
COLOR_ACCENT_HOVER = '#a8f5df'
COLOR_ACCENT_DARK = '#102720'

COLOR_TEXT_WHITE = '#eff5fc'
COLOR_TEXT_LIGHT = '#e8f1fc'
COLOR_TEXT_PRIMARY = '#dce7f5'
COLOR_TEXT_MUTED = '#8ea5b9'
COLOR_TEXT_MUTED_LIGHT = '#9db7cc'
COLOR_TEXT_DIM = '#7994ac'
COLOR_TEXT_SUBTLE = '#6e879e'
COLOR_TEXT_SELECTED = '#c4ffed'
COLOR_TEXT_DELETE = '#ffb6b6'
COLOR_TEXT_DELETE_HOVER = '#ffd0d0'

COLOR_PROGRESS_BG = '#243243'
COLOR_SCROLLBAR_THUMB = '#4a6378'
COLOR_SCROLLBAR_ACTIVE = '#617f98'
COLOR_SCROLLBAR_BORDER = '#263649'
COLOR_BORDER = '#617f98'

