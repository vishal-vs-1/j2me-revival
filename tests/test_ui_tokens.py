"""Unit tests verifying UI design tokens and font resolution."""
from pathlib import Path
import sys
import unittest

import ui_tokens


class UiTokensTests(unittest.TestCase):
    """Verify shared design token definitions and canonical baseline values."""

    def test_canonical_typography_values(self):
        """Verify typography hierarchy retains Windows baseline point sizes."""
        self.assertEqual(ui_tokens.FONT_DISPLAY[1], 24)
        self.assertEqual(ui_tokens.FONT_DISPLAY[2], 'bold')

        self.assertEqual(ui_tokens.FONT_TITLE_LG[1], 23)
        self.assertEqual(ui_tokens.FONT_TITLE_LG[2], 'bold')

        self.assertEqual(ui_tokens.FONT_TITLE_MD[1], 20)
        self.assertEqual(ui_tokens.FONT_TITLE_MD[2], 'bold')

        self.assertEqual(ui_tokens.FONT_COVER_PREVIEW[1], 28)
        self.assertEqual(ui_tokens.FONT_COVER_PREVIEW[2], 'bold')

        self.assertEqual(ui_tokens.FONT_BUTTON_ACCENT[1], 11)
        self.assertEqual(ui_tokens.FONT_BUTTON_ACCENT[2], 'bold')

        self.assertEqual(ui_tokens.FONT_TREEVIEW[1], 11)

        self.assertEqual(ui_tokens.FONT_SECTION_HEADER[1], 10)
        self.assertEqual(ui_tokens.FONT_SECTION_HEADER[2], 'bold')

        self.assertEqual(ui_tokens.FONT_TAB_BUTTON[1], 10)
        self.assertEqual(ui_tokens.FONT_TAB_BUTTON[2], 'bold')

        self.assertEqual(ui_tokens.FONT_BODY[1], 10)
        self.assertEqual(ui_tokens.FONT_BODY_MUTED[1], 9)
        self.assertEqual(ui_tokens.FONT_BADGE[1], 9)
        self.assertEqual(ui_tokens.FONT_CAPTION[1], 8)
        self.assertEqual(ui_tokens.FONT_CAPTION_BOLD[1], 8)

    def test_canonical_padding_values(self):
        """Verify padding tokens maintain generous baseline margins."""
        self.assertEqual(ui_tokens.PAD_RAIL_X, 20)
        self.assertEqual(ui_tokens.PAD_RAIL_Y, 26)
        self.assertEqual(ui_tokens.PAD_RAIL_SUBTITLE_Y, (8, 32))
        self.assertEqual(ui_tokens.PAD_RAIL_SECTION_PADY, 12)
        self.assertEqual(ui_tokens.PAD_RAIL_DEMO_Y, (12, 0))

        self.assertEqual(ui_tokens.PAD_MAIN_X, 20)
        self.assertEqual(ui_tokens.PAD_MAIN_Y, 22)
        self.assertEqual(ui_tokens.PAD_HEADER_Y, (0, 20))

        self.assertEqual(ui_tokens.PAD_DETAIL_X, 20)
        self.assertEqual(ui_tokens.PAD_DETAIL_Y, 16)
        self.assertEqual(ui_tokens.PAD_COVER_X, 14)
        self.assertEqual(ui_tokens.PAD_COVER_Y, 12)
        self.assertEqual(ui_tokens.PAD_TAB_NAV_Y, (16, 8))
        self.assertEqual(ui_tokens.PAD_TAB_BUTTON_PADY, 6)

        self.assertEqual(ui_tokens.PAD_FOOTER_Y, (10, 0))
        self.assertEqual(ui_tokens.PAD_PROGRESS_Y, (8, 10))

    def test_canonical_dimensions(self):
        """Verify baseline dimensions match Windows reference."""
        self.assertEqual(ui_tokens.WIDTH_RAIL, 168)
        self.assertEqual(ui_tokens.BASE_WINDOW_WIDTH, 1140)
        self.assertEqual(ui_tokens.BASE_WINDOW_HEIGHT, 740)
        self.assertEqual(ui_tokens.MIN_WINDOW_WIDTH, 980)
        self.assertEqual(ui_tokens.MIN_WINDOW_HEIGHT, 680)
        self.assertEqual(ui_tokens.ROW_HEIGHT_TREEVIEW, 54)
        self.assertEqual(ui_tokens.WIDTH_TREEVIEW_ACTIONS, 84)

    def test_font_loader_nonexistent_file(self):
        """Verify load_bundled_font safely returns False for missing files."""
        result = ui_tokens.load_bundled_font(Path('/nonexistent/path/font.ttf'))
        self.assertFalse(result)

    def test_font_family_resolution(self):
        """Verify resolve_font_family returns a valid non-empty string."""
        family = ui_tokens.resolve_font_family()
        self.assertIsInstance(family, str)
        self.assertTrue(len(family) > 0)

