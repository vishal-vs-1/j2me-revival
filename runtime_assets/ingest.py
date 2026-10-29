"""Conservative, non-destructive migration of source and verifiable legacy caches."""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import uuid
from PIL import Image

from runtime_assets.contracts import (MAX_SOURCE_PIXELS, Recipe, SourceRecord,
                                      image_source_id, ncnn_recipe, pixel_recipe)
from runtime_assets.store import AssetStore


@dataclass(frozen=True)
class MigrationReport:
    sources_registered: int
    pixel_cache_reused: int
    direct_ai_cache_reused: int
    jobs_queued: int
    invalid_sources: int
    legacy_unknown_cache_files: int


class LegacyCacheImporter:
    """Index validated PNGs; recognize only historical cache routes with exact metadata."""

    PIXEL_LEGACY_LABEL = "scale2x-rgba-v1-4x"
    DIRECT_AI_LEGACY_LABEL = "realesrgan-anime-alpha-v1-4x"

    def __init__(self, workspace: Path, store: AssetStore, *, image_identity=image_source_id):
        self.workspace = Path(workspace).resolve()
        self.store = store
        if self.workspace != store.workspace:
            raise ValueError("Importer and store must target the same workspace")
        self.image_identity = image_identity

    @staticmethod
    def _images(folder: Path):
        if not folder.is_dir():
            return
        for path in sorted(folder.glob("*.png")):
            if path.is_file() and len(path.stem) == 64:
                yield path

    def _source(self, path: Path, origin: str):
        try:
            resolved = path.resolve(strict=True)
            resolved.relative_to(self.workspace)
            with Image.open(resolved) as opened:
                width, height = opened.size
                if width <= 0 or height <= 0 or width * height > MAX_SOURCE_PIXELS:
                    return None
                opened.load()
                image = opened.convert("RGBA")
            identity = self.image_identity(image)
            if identity != path.stem:
                return None
            return SourceRecord(identity, image.width, image.height,
                                resolved.relative_to(self.workspace).as_posix(), origin)
        except (OSError, ValueError, Image.DecompressionBombError):
            return None

    @staticmethod
    def _valid_texture(path: Path, source: SourceRecord, recipe: Recipe) -> bool:
        if not path.is_file():
            return False
        try:
            with Image.open(path) as image:
                image.verify()
            with Image.open(path) as image:
                return image.size == (source.width * recipe.scale, source.height * recipe.scale)
        except (OSError, ValueError, Image.DecompressionBombError):
            return False

    def _normalize_texture(self, source_path: Path, source: SourceRecord,
                           recipe: Recipe) -> str:
        """Copy a verified legacy texture into the recipe-addressed cache without deleting it."""
        relative = f"textures-cache/{recipe.key}/{source.source_id}.png"
        target = self.store.resolve_path(relative)
        if self._valid_texture(target, source, recipe):
            return relative
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + "." + uuid.uuid4().hex + ".tmp")
        try:
            shutil.copyfile(source_path, temporary)
            if not self._valid_texture(temporary, source, recipe):
                raise ValueError("Copied legacy texture failed validation")
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        return relative

    def _legacy_recipe(self, game: dict, ai: Recipe | None):
        if game.get("backend") == "pixel" and game.get("recipe") == self.PIXEL_LEGACY_LABEL:
            return pixel_recipe()
        # Historical AI atlas crops depend on neighbouring atlas entries and
        # placement, which were not recorded. Their files are retained but
        # cannot be safely attached to a per-image runtime recipe.
        report = game.get("asset_decoding", {})
        features = report.get("features", {}) if isinstance(report, dict) else {}
        if not isinstance(features, dict):
            features = {}
        if (game.get("backend") == "ai" and game.get("recipe") == self.DIRECT_AI_LEGACY_LABEL
                and not features.get("batch_ai") and ai is not None
                and game.get("model_digest") == ai.model_digest):
            return ncnn_recipe(game["model_digest"], legacy_direct=True)
        return None

    def import_workspace(self, game: dict, selected_recipe: Recipe,
                         *, ai_recipe: Recipe | None = None, priority: int = 0,
                         queue_missing: bool = True) -> MigrationReport:
        """Register originals/captures and queue work while preserving every legacy file."""
        if game.get("id") != self.workspace.name:
            raise ValueError("Game metadata ID does not match the workspace")
        self.store.register_recipe(selected_recipe)
        if ai_recipe is not None:
            self.store.register_recipe(ai_recipe)
        known_recipe = self._legacy_recipe(game, ai_recipe)
        if known_recipe is not None:
            self.store.register_recipe(known_recipe)
        candidates = []
        for folder, origin in ((self.workspace / "original-assets", "legacy-original"),
                               (self.workspace / "captures", "legacy-capture")):
            candidates.extend((path, origin) for path in self._images(folder) or ())

        registered = pixel_reused = ai_reused = queued = invalid = 0
        adopted_cache_paths = set()
        for path, origin in candidates:
            source = self._source(path, origin)
            if source is None:
                invalid += 1
                continue
            self.store.register_source(source)
            registered += 1

            existing = self.store.get_job(source.source_id, selected_recipe.key)
            if existing is not None and existing.state == "READY" and existing.relative_output:
                ready = self.store.resolve_path(existing.relative_output)
                if self._valid_texture(ready, source, selected_recipe):
                    relative = self._normalize_texture(ready, source, selected_recipe)
                    self.store.mark_imported_ready(source.source_id, selected_recipe.key, relative)
                    adopted_cache_paths.add(relative)
                    continue

            adopted = False
            if known_recipe is not None:
                # Old text/digit overrides have no source-level recipe record;
                # never classify those pixels as the generic pixel recipe.
                if not (self.workspace / "textures-ui" / (source.source_id + ".png")).is_file():
                    old_dir = "textures" if known_recipe.algorithm == "scale2x-rgba" else "textures-ai"
                    relative = f"{old_dir}/{source.source_id}.png"
                    old_path = self.store.resolve_path(relative)
                    known_job = self.store.get_job(source.source_id, known_recipe.key)
                    if (not (known_job and known_job.state == "RUNNING") and
                            self._valid_texture(old_path, source, known_recipe)):
                        canonical = self._normalize_texture(old_path, source, known_recipe)
                        adopted = self.store.mark_imported_ready(source.source_id,
                                                                 known_recipe.key, canonical)
                        if adopted:
                            adopted_cache_paths.add(canonical)
                        if adopted and known_recipe.algorithm == "scale2x-rgba":
                            pixel_reused += 1
                        elif adopted:
                            ai_reused += 1
            if queue_missing and (known_recipe is None or known_recipe.key != selected_recipe.key or not adopted):
                queued += int(self.store.enqueue(source.source_id, selected_recipe.key,
                                                 priority, force=True))

        # Preserve and count every cache whose source/recipe could not be verified.
        legacy_unknown = 0
        for name in ("textures", "textures-ai", "textures-ui"):
            directory = self.workspace / name
            if directory.is_dir():
                legacy_unknown += sum(1 for path in directory.glob("*.png")
                                      if path.is_file() and
                                      path.relative_to(self.workspace).as_posix() not in adopted_cache_paths)
        return MigrationReport(registered, pixel_reused, ai_reused, queued, invalid, legacy_unknown)
