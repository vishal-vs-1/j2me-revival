"""Thin, injectable wrappers around the existing deterministic and NCNN algorithms."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Callable

from PIL import Image

from runtime_assets.contracts import EnhancementBackend, Recipe, pixel_recipe


def model_weights_digest(model_directory: Path) -> str:
    """Digest exact model filenames and bytes; do not include a GPU path or device name."""
    directory = Path(model_directory).resolve()
    filenames = ("realesrgan-x4plus-anime.param", "realesrgan-x4plus-anime.bin")
    digest = hashlib.sha256()
    for name in filenames:
        path = directory / name
        if not path.is_file():
            raise FileNotFoundError(f"Required NCNN model file is missing: {path}")
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
    return digest.hexdigest()


class PixelBackend:
    algorithm = "scale2x-rgba"

    def __init__(self, scale_image: Callable[[Image.Image], Image.Image]):
        self._scale_image = scale_image

    def enhance(self, source: Image.Image, recipe: Recipe, workdir: Path) -> Image.Image:
        self._validate_recipe(recipe)
        from runtime_assets.resources import host_memory,ResourcePressure
        available=host_memory()['available_bytes']
        if available and source.width*source.height*256>available//3:
            raise ResourcePressure('Waiting for system memory before preparing this large CPU image.')
        rgba = source.convert("RGBA")
        result = self._scale_image(rgba)
        if result.size != (rgba.width * recipe.scale, rgba.height * recipe.scale):
            raise ValueError("Pixel backend returned unexpected image dimensions")
        return result.convert("RGBA")

    @classmethod
    def _validate_recipe(cls, recipe: Recipe):
        if recipe != pixel_recipe():
            raise ValueError("PixelBackend received an incompatible recipe")


class NcnnBackend:
    algorithm = "realesrgan-x4plus-anime"

    def __init__(self, *, model_directory: Path | None = None,
                 upscale: Callable | None = None, model_digest: str | None = None):
        self.model_directory = Path(model_directory).resolve() if model_directory else None
        self._upscale = upscale
        if model_digest is not None:
            if (not isinstance(model_digest, str) or len(model_digest) != 64 or
                    any(c not in "0123456789abcdef" for c in model_digest)):
                raise ValueError("Injected model digest must be lowercase SHA-256 hex")
            self.model_digest = model_digest
        elif self.model_directory is not None:
            self.model_digest = model_weights_digest(self.model_directory)
        else:
            self.model_digest = None

    def recipe(self) -> Recipe:
        if self.model_digest is None:
            from ai_backend import executable
            binary = executable()
            if binary is None:
                raise RuntimeError("Install the free local AI backend before selecting its recipe")
            self.model_directory = binary.parent / "models"
            self.model_digest = model_weights_digest(self.model_directory)
        return Recipe(
            schema=1,
            algorithm=self.algorithm,
            implementation_version="realesrgan-ncnn-alpha-v1-4x",
            model_digest=self.model_digest,
            scale=4,
            alpha_policy="source-alpha-extruded-rgb-v1",
            border_policy="8px-edge-pad-crop-v1",
            settings={"jobs": "1:1:1", "tile_size": 128},
        )

    def enhance(self, source: Image.Image, recipe: Recipe, workdir: Path) -> Image.Image:
        if self.model_digest is None or recipe != self.recipe():
            raise ValueError("NcnnBackend received an incompatible recipe")
        if self._upscale is None:
            from ai_backend import upscale
            operation = upscale
        else:
            operation = self._upscale
        rgba = source.convert("RGBA")
        result = operation(rgba, Path(workdir), rgba.getchannel("A"))
        if result.size != (rgba.width * recipe.scale, rgba.height * recipe.scale):
            raise ValueError("NCNN backend returned unexpected image dimensions")
        return result.convert("RGBA")


    def enhance_many(self, sources: list[Image.Image], recipe: Recipe,
                     workdir: Path) -> list[Image.Image]:
        """Reuse one NCNN model/context without joining unrelated sprites into an atlas."""
        if self.model_digest is None or recipe != self.recipe():
            raise ValueError("NcnnBackend received an incompatible recipe")
        if self._upscale is not None:
            return [self.enhance(source, recipe, workdir) for source in sources]
        from ai_backend import upscale_many
        budget=self.batch_limits()
        if budget.reason:
            from runtime_assets.resources import ResourcePressure
            raise ResourcePressure(budget.reason)
        # Image-level concurrency changes scheduling, not the model or spatial
        # tiling. Keep the historical reference recipe/cache identity intact.
        small=all(source.width*source.height<=4096 and max(source.size)<=128 for source in sources)
        threads=budget.processing_threads if small else 1
        results = upscale_many(sources, Path(workdir), processing_threads=threads)
        if len(results) != len(sources):
            raise ValueError("NCNN batch returned an unexpected image count")
        for source, result in zip(sources, results):
            if result.size != (source.width * recipe.scale, source.height * recipe.scale):
                raise ValueError("NCNN batch returned unexpected image dimensions")
        return [result.convert("RGBA") for result in results]

    def batch_limits(self):
        from runtime_assets.resources import current_budget
        return current_budget()


class BackendRegistry:
    """Select an injected algorithm implementation from its recipe, never from a game."""

    def __init__(self, backends):
        self._backends = {}
        for backend in backends:
            algorithm = getattr(backend, "algorithm", None)
            if not algorithm or algorithm in self._backends:
                raise ValueError("Every backend must declare a unique algorithm")
            self._backends[algorithm] = backend

    def get(self, recipe: Recipe) -> EnhancementBackend:
        try:
            return self._backends[recipe.algorithm]
        except KeyError as error:
            raise LookupError(f"No enhancement backend is registered for {recipe.algorithm!r}") from error
