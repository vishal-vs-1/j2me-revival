from pathlib import Path
import tempfile,unittest,zipfile
from game_inspection import inspect

class GameInspectionTests(unittest.TestCase):
    def test_packed_graphics_are_reported_as_partial_evidence(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'build') as folder:
            jar=Path(folder)/'packed.jar'
            with zipfile.ZipFile(jar,'w') as out:
                out.writestr('b.class',b'drawRegion createRGBImage')
                out.writestr('7',b'packed pixels')
                out.writestr('icon.png',b'icon')
            report=inspect(jar,1)
            self.assertTrue(report['packed_graphics_likely'])
            self.assertTrue(report['custom_sprite_engine_likely'])
            self.assertEqual(report['drawing_evidence']['draw_region'],['b.class'])
            self.assertFalse(report['drawing_evidence']['m3g'])
            plan=report['handling_plan'];kinds={path['kind'] for path in plan['paths']}
            self.assertTrue({'source_images','region_sprites','decoded_or_generated_pixels','packed_graphics'}<=kinds)
            self.assertEqual(plan['primary_strategy'],'packed_2d_with_custom_decoding')
            self.assertIsNone(plan['complete_hd_coverage']);self.assertFalse(plan['runtime_validated'])
    def test_standalone_assets_do_not_claim_complete_coverage(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'build') as folder:
            jar=Path(folder)/'simple.jar'
            with zipfile.ZipFile(jar,'w') as out:
                out.writestr('Main.class',b'javax/microedition/lcdui/game/Sprite drawRegion')
                out.writestr('sheet.png',b'sheet')
            report=inspect(jar,4)
            self.assertFalse(report['packed_graphics_likely'])
            self.assertFalse(report['custom_sprite_engine_likely'])
            self.assertIn('has not been measured',report['coverage_note'])
            self.assertEqual(report['handling_plan']['primary_strategy'],'source_images_and_regions')

    def test_mixed_rendering_keeps_all_handlers_and_3d_limit(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'build') as folder:
            jar=Path(folder)/'mixed.jar'
            with zipfile.ZipFile(jar,'w') as out:
                out.writestr('Main.class',b'drawRegion drawRGB javax/microedition/m3g javax/microedition/lcdui/Font')
                out.writestr('FONT.png',b'font')
            plan=inspect(jar,5)['handling_plan']
            paths={path['kind']:path for path in plan['paths']}
            self.assertEqual(plan['primary_strategy'],'3d_or_mixed_2d_3d')
            self.assertIn('region_sprites',paths);self.assertIn('decoded_or_generated_pixels',paths)
            self.assertIn('bitmap_fonts',paths);self.assertIn('system_text',paths)
            self.assertEqual(paths['three_d']['support'],'compatibility_output_only')
