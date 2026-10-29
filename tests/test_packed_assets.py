"""The packed sprite importer must keep identities, alpha and game scopes intact."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from engine import enhance, image_id
from atlas_enhancement import enhance_decoded_ai


class PackedAssetsTest(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1] / 'build' / 'test-temp'
        root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)

    def test_atlas_preserves_each_sprite_size_and_transparency(self):
        source = self.folder / 'sources'
        source.mkdir()
        items = []
        for size, color in [((8, 8), (255, 0, 0, 255)),
                            ((22, 20), (0, 200, 20, 255)),
                            ((35, 30), (30, 20, 240, 255))]:
            sprite = Image.new('RGBA', size)
            for y in range(2, size[1] - 2):
                for x in range(2, size[0] - 2):
                    sprite.putpixel((x, y), color)
            key = image_id(sprite)
            path = source / (key + '.png')
            sprite.save(path)
            items.append((key, path))
        def fake_ai(image, folder, alpha):
            result = enhance(image)
            result.putalpha(alpha)
            return result
        with patch('ai_backend.upscale', side_effect=fake_ai):
            count = enhance_decoded_ai(self.folder, items, self.folder / 'textures', enhance)
        self.assertEqual(count, len(items))
        for key, path in items:
            with Image.open(path) as original, Image.open(self.folder / 'textures' / (key + '.png')) as texture:
                self.assertEqual(texture.size, (original.width * 4, original.height * 4))
                self.assertEqual(texture.getpixel((0, 0))[3], 0)
                self.assertGreater(texture.getpixel((original.width * 2, original.height * 2))[3], 0)


if __name__ == '__main__':
    unittest.main()
