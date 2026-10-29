"""Batch source images for enhancement; decoding and playback are separate stages."""
from pathlib import Path
import os
from PIL import Image


def enhance_decoded_ai(folder: Path, sources: list[tuple[str, Path]], target: Path,
                       pixel_enhance, progress=lambda message: None) -> int:
    """Batch independent sprites into padded atlases instead of starting AI per tiny image."""
    from ai_backend import upscale
    target.mkdir(parents=True, exist_ok=True)
    pending = [(key, path) for key, path in sources if not (target / (key + '.png')).exists()]
    if not pending:
        return 0
    small = []
    larger = []
    for key, path in pending:
        with Image.open(path) as source:
            size = source.size
        (small if size[0] * size[1] < 256 else larger).append((key, path))
    completed = 0
    # Very small modules have too little information for the neural model.
    for key, path in small:
        with Image.open(path) as source:
            result = pixel_enhance(source.convert('RGBA'))
        _save_texture(target / (key + '.png'), result)
        completed += 1
    progress(f'Prepared {completed} tiny modules with edge-aware 4× scaling.')
    def height(item):
        with Image.open(item[1]) as source:
            return source.height
    larger.sort(key=height, reverse=True)
    atlas = Image.new('RGBA', (512, 512))
    placements = []
    x = y = row_height = 0
    batch_index = 0
    def finish(image, items):
        nonlocal completed, batch_index
        alpha = pixel_enhance(image).getchannel('A')
        output = upscale(image, folder, alpha)
        for key, left, top, width, height in items:
            result = output.crop((left * 4, top * 4, (left + width) * 4, (top + height) * 4))
            _save_texture(target / (key + '.png'), result)
            completed += 1
        batch_index += 1
        progress(f'Enhanced sprite atlas {batch_index} • {completed}/{len(pending)} images')
    for key, path in larger:
        with Image.open(path) as source:
            sprite = source.convert('RGBA')
        width, height = sprite.size
        padded_width, padded_height = width + 32, height + 32
        if padded_width > 512 or padded_height > 512:
            alpha = pixel_enhance(sprite).getchannel('A')
            _save_texture(target / (key + '.png'), upscale(sprite, folder, alpha))
            completed += 1
            continue
        if x + padded_width > 512:
            x = 0
            y += row_height
            row_height = 0
        if y + padded_height > 512:
            finish(atlas, placements)
            atlas = Image.new('RGBA', (512, 512))
            placements = []
            x = y = row_height = 0
        atlas.alpha_composite(sprite, (x + 16, y + 16))
        placements.append((key, x + 16, y + 16, width, height))
        x += padded_width
        row_height = max(row_height, padded_height)
    if placements:
        finish(atlas, placements)
    return completed


def _save_texture(path: Path, image: Image.Image) -> None:
    temporary = path.with_suffix('.tmp')
    image.save(temporary, format='PNG')
    os.replace(temporary, path)
