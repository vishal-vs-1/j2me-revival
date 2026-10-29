"""Immutable, title-independent records shared by import and runtime asset work."""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import math
from pathlib import PurePosixPath
import re
import struct
from types import MappingProxyType
from typing import Mapping, Protocol, runtime_checkable

import numpy as np
from PIL import Image

MAX_SOURCE_PIXELS = 4_194_304
SOURCE_ID_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _freeze_json(value, path="$", depth=0):
    if depth > 32:
        raise ValueError("Recipe settings are nested too deeply")
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"Recipe setting {path} must be a finite number")
        return value
    if isinstance(value, Mapping):
        result = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"Recipe setting keys must be strings: {path}")
            result[key] = _freeze_json(item, f"{path}.{key}", depth + 1)
        return MappingProxyType(result)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item, f"{path}[{index}]", depth + 1)
                     for index, item in enumerate(value))
    raise TypeError(f"Recipe settings must contain JSON values, found {type(value).__name__} at {path}")


def _thaw_json(value):
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


@dataclass(frozen=True)
class Recipe:
    schema: int
    algorithm: str
    implementation_version: str
    model_digest: str
    scale: int
    alpha_policy: str
    border_policy: str
    settings: Mapping = field(default_factory=dict)

    def __post_init__(self):
        if isinstance(self.schema, bool) or not isinstance(self.schema, int) or self.schema < 1:
            raise ValueError("Recipe schema must be positive")
        for name in ("algorithm", "implementation_version", "alpha_policy", "border_policy"):
            value = getattr(self, name)
            if not value or not isinstance(value, str) or len(value) > 128:
                raise ValueError(f"Recipe {name} must be a non-empty string up to 128 characters")
        if isinstance(self.scale, bool) or not isinstance(self.scale, int) or self.scale not in (1, 2, 3, 4):
            raise ValueError("Recipe scale must be between 1 and 4")
        if (not isinstance(self.model_digest, str) or
                (self.model_digest and not SOURCE_ID_PATTERN.fullmatch(self.model_digest))):
            raise ValueError("Model digest must be empty or a lowercase SHA-256 hex digest")
        if not isinstance(self.settings, Mapping):
            raise TypeError("Recipe settings must be a JSON object")
        frozen = _freeze_json(self.settings)
        # Validate the complete representation once, so serialization cannot fail later.
        json.dumps(_thaw_json(frozen), sort_keys=True, separators=(",", ":"),
                   ensure_ascii=False, allow_nan=False)
        object.__setattr__(self, "settings", frozen)

    def document(self) -> dict:
        return {
            "schema": self.schema,
            "algorithm": self.algorithm,
            "implementation_version": self.implementation_version,
            "model_digest": self.model_digest,
            "scale": self.scale,
            "alpha_policy": self.alpha_policy,
            "border_policy": self.border_policy,
            "settings": _thaw_json(self.settings),
        }

    def canonical_json(self) -> str:
        return json.dumps(self.document(), sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False)

    @property
    def key(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @classmethod
    def from_json(cls, raw: str) -> "Recipe":
        try:
            value = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as error:
            raise ValueError("Invalid canonical recipe JSON") from error
        if not isinstance(value, dict) or set(value) != {
            "schema", "algorithm", "implementation_version", "model_digest", "scale",
            "alpha_policy", "border_policy", "settings",
        }:
            raise ValueError("Recipe JSON has missing or unknown fields")
        recipe = cls(**value)
        if recipe.canonical_json() != raw:
            raise ValueError("Stored recipe JSON is not canonical")
        return recipe


def pixel_recipe() -> Recipe:
    """The current deterministic 4x pixel recipe used by engine.enhance."""
    return Recipe(
        schema=1,
        algorithm="scale2x-rgba",
        implementation_version="scale2x-rgba-v1-4x",
        model_digest="",
        scale=4,
        alpha_policy="transparent-rgb-zero-v1",
        border_policy="edge-repeat-v1",
        settings={"passes": 2},
    )


def ncnn_recipe(model_digest: str, *, legacy_direct: bool = False) -> Recipe:
    """Current single-image NCNN recipe; device selection is deliberately excluded."""
    if not isinstance(model_digest, str) or not SOURCE_ID_PATTERN.fullmatch(model_digest):
        raise ValueError("NCNN recipe requires a lowercase SHA-256 model digest")
    version = "realesrgan-ncnn-alpha-v1-4x"
    if legacy_direct:
        version = "realesrgan-anime-alpha-v1-4x"
    return Recipe(
        schema=1,
        algorithm="realesrgan-x4plus-anime",
        implementation_version=version,
        model_digest=model_digest,
        scale=4,
        alpha_policy="source-alpha-extruded-rgb-v1",
        border_policy="8px-edge-pad-crop-v1",
        settings={"jobs": "1:1:1", "tile_size": 128},
    )


def image_source_id(image: Image.Image) -> str:
    """Canonical identity shared with the existing Java enhancement hash."""
    width, height = image.size
    if width <= 0 or height <= 0 or width * height > MAX_SOURCE_PIXELS:
        raise ValueError("Source image dimensions are outside the supported limit")
    pixels = np.asarray(image.convert("RGBA"), dtype=np.uint8).copy()
    pixels[pixels[:, :, 3] == 0, :3] = 0
    return hashlib.sha256(struct.pack(">II", width, height) + pixels.tobytes()).hexdigest()


class SourceKind:
    RESOURCE = "resource"
    ENCODED = "encoded"
    RGB = "rgb"
    MUTABLE_SNAPSHOT = "mutable-snapshot"
    DERIVED = "derived"
    LEGACY_ORIGINAL = "legacy-original"
    LEGACY_CAPTURE = "legacy-capture"


@dataclass(frozen=True)
class SourceRecord:
    source_id: str
    width: int
    height: int
    relative_path: str
    origin: str

    def __post_init__(self):
        if not isinstance(self.source_id, str) or not SOURCE_ID_PATTERN.fullmatch(self.source_id):
            raise ValueError("Source ID must be a lowercase SHA-256 hex digest")
        if (isinstance(self.width, bool) or not isinstance(self.width, int) or
                isinstance(self.height, bool) or not isinstance(self.height, int) or
                self.width <= 0 or self.height <= 0 or
                self.width * self.height > MAX_SOURCE_PIXELS):
            raise ValueError("Source image dimensions are outside the supported limit")
        if not isinstance(self.origin, str) or not self.origin or len(self.origin) > 64:
            raise ValueError("Source origin must be a short non-empty label")
        if not isinstance(self.relative_path, str) or not self.relative_path or "\x00" in self.relative_path:
            raise ValueError("Source path must be a non-empty relative POSIX path")
        path = PurePosixPath(self.relative_path)
        if (path.is_absolute() or not path.parts or
                any(part in (".", "..") or ":" in part for part in path.parts)):
            raise ValueError("Source path must be relative to its game workspace")
        if "\\" in self.relative_path or "\x00" in self.relative_path:
            raise ValueError("Source path must use safe POSIX separators")


@runtime_checkable
class EnhancementBackend(Protocol):
    algorithm: str

    def enhance(self, source: Image.Image, recipe: Recipe, workdir) -> Image.Image: ...
