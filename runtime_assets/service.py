"""Shared, non-blocking coordinator for imported and filesystem-discovered artwork."""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
import os
from pathlib import Path, PurePosixPath
import queue
import shutil
import tempfile
import threading
import time
import uuid
from typing import Callable, Iterable

from PIL import Image

from runtime_assets.contracts import Recipe, SourceRecord, image_source_id
from runtime_assets.ingest import LegacyCacheImporter, MigrationReport
from runtime_assets.store import AssetStore, JobLease, JobRecord
from runtime_assets.resources import ResourcePressure


@dataclass
class _Game:
    workspace: Path
    store: AssetStore
    recipe: Recipe
    paused: bool = False
    generation: int = 0
    dirty_at: float | None = None
    next_scan: float = 0.0
    compat_pending: bool = True
    compat_recipe_key: str = ""
    compat_sources: set[str] | None = None
    player_active: bool = False
    metrics_path: Path | None = None
    live_enabled: bool = True
    live_reason: str = "Background preparation ready"
    metric_checked_at: float = 0.0
    metric_updated: float = 0.0
    metric_sampled: float = 0.0
    metric_values: dict | None = None
    baseline_frames: list[float] = field(default_factory=list)
    baseline_inputs: list[float] = field(default_factory=list)
    baseline_fps: list[float] = field(default_factory=list)
    last_live_job_at: float = 0.0
    last_live_job_seconds: float = 0.0
    live_jobs_started: int = 0
    batch_fallbacks: int = 0
    batch_limit: int = 16
    resource_reason: str = ''
    removing: bool = False


@dataclass(frozen=True)
class _Work:
    game: _Game
    lease: JobLease
    source: SourceRecord
    recipe: Recipe


@dataclass(frozen=True)
class _Batch:
    items: tuple[_Work, ...]


@dataclass(frozen=True)
class _Outcome:
    work: _Work
    output: str | None
    error: str | None
    elapsed: float
    retry_single: bool = False
    resource_defer: bool = False


class AssetService:
    """One coordinator and GPU worker; idle work can share one model run per batch."""

    def __init__(self, backend_factory: Callable[[Recipe], object], *,
                 listener: Callable[[str, dict], None] | None = None,
                 poll_seconds: float = 0.1, lease_seconds: float = 90.0,
                 batch_size: int = 512, batch_pixels: int = 1_048_576):
        self._backend_factory = backend_factory
        self._listener = listener
        self._poll_seconds = max(0.02, float(poll_seconds))
        self._lease_seconds = max(15.0, float(lease_seconds))
        self._batch_size = max(1, min(512, int(batch_size)))
        self._batch_pixels = max(1, min(4_194_304, int(batch_pixels)))
        self._batch_disabled: set[str] = set()
        self._owner = "asset-service-" + uuid.uuid4().hex
        self._games: dict[str, _Game] = {}
        self._paused_all = False
        self._lock = threading.RLock()
        self._compat_commit_lock = threading.Lock()
        self._coordinator_gate = threading.RLock()
        self._stop = threading.Event()
        self._work: queue.Queue[_Batch | None] = queue.Queue(maxsize=1)
        self._outcomes: queue.Queue[_Outcome] = queue.Queue()
        self._coordinator: threading.Thread | None = None
        self._worker: threading.Thread | None = None
        self._active: _Batch | None = None
        self._lease_renew_at = 0.0
        self._cursor = 0
        self._closed = False

    def set_listener(self, listener: Callable[[str, dict], None] | None):
        self._listener = listener

    def _notify(self, game_id: str):
        listener = self._listener
        if listener is None:
            return
        try:
            listener(game_id, self.stats(game_id))
        except Exception:
            pass

    def _start(self):
        with self._lock:
            if self._closed:
                raise RuntimeError("AssetService is closed")
            if self._coordinator is not None:
                return
            self._stop.clear()
            self._worker = threading.Thread(target=self._worker_loop,
                                            name="asset-enhancer", daemon=True)
            self._coordinator = threading.Thread(target=self._coordinator_loop,
                                                 name="asset-coordinator", daemon=True)
            self._worker.start()
            self._coordinator.start()

    def register_game(self, workspace: Path, recipe: Recipe, *, game: dict,
                      ai_recipe: Recipe | None = None, queue_missing: bool = True,
                      paused: bool = False) -> MigrationReport:
        """Register a game and its static sources without waiting for enhancement."""
        with self._coordinator_gate:
            return self._register_game(workspace,recipe,game=game,ai_recipe=ai_recipe,
                                       queue_missing=queue_missing,paused=paused)

    def _register_game(self,workspace,recipe,*,game,ai_recipe,queue_missing,paused):
        root = Path(workspace).resolve()
        if game.get("id") != root.name:
            raise ValueError("Game metadata ID does not match its workspace")
        store = AssetStore(root)
        report = LegacyCacheImporter(root, store).import_workspace(
            game, recipe, ai_recipe=ai_recipe, queue_missing=queue_missing)
        with self._lock:
            current = self._games.get(root.name)
            if current is None:
                key, sources = self._read_compatibility_state(root, recipe.key)
                current = _Game(root, store, recipe, paused=paused or self._paused_all,
                                compat_recipe_key=key, compat_sources=sources)
                self._games[root.name] = current
            else:
                if current.recipe.key != recipe.key:
                    current.compat_recipe_key = ""
                    current.compat_sources = set()
                current.store = store
                current.recipe = recipe
                current.paused = paused or self._paused_all
            current.dirty_at = time.monotonic() + 0.5
            current.next_scan = time.monotonic() + 5.0
            current.compat_pending = True
        self._start()
        self._notify(root.name)
        return report

    def register_imported_sources(self, workspace: Path,
                                  sources: Iterable[SourceRecord]) -> int:
        """Validate and queue a batch of imported sources under the selected recipe."""
        game = self._game_for(workspace)
        added = 0
        for source in sources:
            if not isinstance(source, SourceRecord):
                raise TypeError("Imported asset batches must contain SourceRecord values")
            path = game.store.resolve_path(source.relative_path)
            verified = self._read_source(path, source.source_id)
            if (verified.width, verified.height) != (source.width, source.height):
                raise ValueError("Imported source dimensions do not match its record")
            game.store.register_source(source)
            added += int(game.store.enqueue(source.source_id, game.recipe.key))
        if added:
            self._notify(game.workspace.name)
        return added

    def select_recipe(self, game_id: str, recipe: Recipe):
        game = self._game(game_id)
        game.store.register_recipe(recipe)
        with self._lock:
            if game.recipe.key != recipe.key:
                game.compat_recipe_key = ""
                game.compat_sources = set()
            game.recipe = recipe
            game.dirty_at = time.monotonic() + 0.5
            game.compat_pending = True
        added = 0
        for source in game.store.list_sources():
            added += int(game.store.enqueue(source.source_id, recipe.key))
        self._start()
        self._notify(game_id)
        return added

    def pause(self, game_id: str):
        with self._compat_commit_lock:
            with self._lock:
                self._game(game_id).paused = True

    def resume(self, game_id: str):
        with self._lock:
            game = self._game(game_id)
            game.paused = False
            game.compat_pending = True

    def pause_all(self):
        with self._compat_commit_lock:
            with self._lock:
                self._paused_all = True
                for game in self._games.values():
                    game.paused = True

    def resume_all(self):
        with self._lock:
            self._paused_all = False
            for game in self._games.values():
                game.paused = not game.live_enabled
                if not game.paused:
                    game.compat_pending = True

    def set_player_state(self, game_id: str, running: bool, metrics_path: Path | None = None,
                         *, allow_live: bool = True):
        """Attach fresh local player metrics and enable conservative live admission."""
        game = self._game(game_id)
        metrics = Path(metrics_path).resolve() if metrics_path is not None else None
        changed = False
        with self._lock:
            changed = (game.player_active != bool(running) or
                       game.metrics_path != (metrics if running else None) or
                       game.live_enabled != bool(allow_live))
            started = running and (not game.player_active or game.metrics_path != metrics)
            game.player_active = bool(running)
            game.metrics_path = metrics if running else None
            game.live_enabled = bool(allow_live)
            game.paused = self._paused_all or (running and not allow_live)
            if started:
                game.metric_checked_at = 0.0
                game.metric_updated = 0.0
                game.metric_sampled = 0.0
                game.metric_values = None
                game.baseline_frames.clear()
                game.baseline_inputs.clear()
                game.baseline_fps.clear()
                game.last_live_job_at = 0.0
                game.live_reason = "Measuring game performance before live image work"
            elif not running:
                game.metric_values = None
                game.baseline_frames.clear()
                game.baseline_inputs.clear()
                game.baseline_fps.clear()
                game.live_reason = "Background preparation ready"
                game.paused = self._paused_all
            elif not allow_live:
                game.live_reason = "Live image work paused by the user"
            elif game.live_reason == "Live image work paused by the user":
                game.live_reason = "Measuring game performance before live image work"
                changed = True
        if changed:
            self._notify(game_id)

    def stats(self, game_id: str) -> dict:
        game = self._game(game_id)
        counts = game.store.counts(game.recipe.key)
        active = self._active
        counts.update(game_id=game_id, recipe_key=game.recipe.key,
                      paused=game.paused, total=sum(counts[state] for state in
                      ("QUEUED", "RUNNING", "DEFERRED", "READY", "FAILED")),
                      player_active=game.player_active,
                      live_enabled=game.live_enabled,
                      live_reason=game.live_reason,
                      live_jobs_started=game.live_jobs_started,
                      last_live_job_seconds=game.last_live_job_seconds,
                      active_batch_images=sum(work.game is game for work in active.items) if active else 0,
                      background_batch_limit=game.batch_limit,
                      batch_fallbacks=game.batch_fallbacks,
                      resource_reason=game.resource_reason,
                      frame_p95_ms=(game.metric_values or {}).get("frame_p95_ms"),
                      input_queue_p95_ms=(game.metric_values or {}).get("input_queue_p95_ms"))
        return counts

    def reconcile(self, game_id: str) -> int:
        """Import newly published source PNGs and process a bounded event batch."""
        with self._coordinator_gate:
            game = self._game(game_id)
            return self._reconcile_sources(game) + self._ingest_events(game, 32)

    def unregister_game(self,game_id: str,*,timeout: float=60.0) -> bool:
        """Quiesce one game's writes before its files are removed; other games stay registered."""
        deadline=time.monotonic()+max(0.0,timeout)
        with self._coordinator_gate:
            with self._lock:
                game=self._games.get(game_id)
                if game is None:return False
                if game.player_active:
                    raise RuntimeError('Close the game before deleting it so its saves can finish writing.')
                was_paused=game.paused
                game.removing=True
                game.paused=True
        while True:
            with self._coordinator_gate:
                self._drain_outcomes()
                if self._active is None or all(work.game is not game for work in self._active.items):
                    with self._lock:self._games.pop(game_id,None)
                    return True
                if time.monotonic()>=deadline:
                    with self._lock:
                        game.removing=False
                        game.paused=was_paused or self._paused_all
                    raise TimeoutError('The current artwork batch is still finishing. Try deleting again when it finishes.')
            time.sleep(0.05)

    def _game(self, game_id: str) -> _Game:
        with self._lock:
            try:
                return self._games[game_id]
            except KeyError as error:
                raise KeyError(f"Game {game_id!r} is not registered with AssetService") from error

    def _game_for(self, workspace: Path) -> _Game:
        root = Path(workspace).resolve()
        game = self._game(root.name)
        if game.workspace != root:
            raise ValueError("Workspace does not match the registered game")
        return game

    @staticmethod
    def _read_source(path: Path, expected_id: str | None = None) -> Image.Image:
        with Image.open(path) as decoded:
            width, height = decoded.size
            if width <= 0 or height <= 0 or width * height > 4_194_304:
                raise ValueError("Source image dimensions are outside the supported limit")
            decoded.load()
            image = decoded.convert("RGBA")
        source_id = image_source_id(image)
        if expected_id is not None and source_id != expected_id:
            raise ValueError("Source pixels do not match their source ID")
        return image

    def _reconcile_sources(self, game: _Game) -> int:
        known = {source.source_id for source in game.store.list_sources()}
        registered = 0
        directory = game.workspace / "original-assets"
        if directory.is_dir():
            for path in sorted(directory.glob("*.png")):
                if len(path.stem) != 64 or path.stem in known:
                    continue
                try:
                    resolved = path.resolve(strict=True)
                    resolved.relative_to(game.workspace)
                    image = self._read_source(resolved, path.stem)
                    source = SourceRecord(path.stem, image.width, image.height,
                                          resolved.relative_to(game.workspace).as_posix(),
                                          "legacy-original")
                    game.store.register_source(source)
                    game.store.enqueue(source.source_id, game.recipe.key)
                    known.add(source.source_id)
                    registered += 1
                except (OSError, ValueError):
                    continue
        if registered:
            self._notify(game.workspace.name)
        return registered

    def _ingest_events(self, game: _Game, limit: int) -> int:
        event_dir = game.workspace / ".runtime" / "events"
        if not event_dir.is_dir():
            return 0
        accepted = 0
        for event_path in sorted(event_dir.glob("*.json"))[:limit]:
            try:
                event = json.loads(event_path.read_text(encoding="utf-8"))
                if (not isinstance(event, dict) or event.get("schema") != 1 or
                        event.get("type") != "capture-ready"):
                    raise ValueError("Unsupported capture event")
                event_id = event.get("event_id")
                source_id = event.get("source_id")
                relative = event.get("source_path")
                source_parts = PurePosixPath(relative).parts if isinstance(relative, str) else ()
                if (not isinstance(source_id, str) or len(source_id) != 64 or
                        not source_parts or source_parts[0] not in ("original-assets", "captures") or
                        PurePosixPath(relative).stem != source_id):
                    raise ValueError("Capture event source path is invalid")
                source_path = game.store.resolve_path(relative)
                source_path.resolve(strict=True).relative_to(game.workspace)
                image = self._read_source(source_path, source_id)
                if (event.get("width"), event.get("height")) != image.size:
                    raise ValueError("Capture event dimensions do not match its image")
                origin = event.get("origin")
                if not isinstance(origin, str) or not origin or len(origin) > 64:
                    raise ValueError("Capture event origin is invalid")
                source = SourceRecord(source_id, image.width, image.height, relative, origin)
                game.store.register_capture_event(event_id, source, game.recipe)
                event_path.unlink(missing_ok=True)
                accepted += 1
            except (OSError, ValueError, TypeError, KeyError):
                # A malformed service-owned event is isolated so it cannot block later events.
                rejected = game.workspace / ".runtime" / "rejected-events"
                rejected.mkdir(parents=True, exist_ok=True)
                try:
                    os.replace(event_path, rejected / (event_path.name + "." + uuid.uuid4().hex))
                except OSError:
                    pass
        if accepted:
            game.dirty_at = time.monotonic() + 0.5
            self._notify(game.workspace.name)
        return accepted

    def _coordinator_loop(self):
        while not self._stop.wait(self._poll_seconds):
            with self._coordinator_gate:self._coordinate_once()

    def _coordinate_once(self):
        now = time.monotonic()
        with self._lock:
            games = list(self._games.values())
        for game in games:
            if game.removing:continue
            try:
                game.store.recover_expired()
                if now >= game.next_scan:
                    self._reconcile_sources(game)
                    game.next_scan = now + 5.0
                if self._ingest_events(game, 32):
                    game.dirty_at = now + 0.5
            except Exception:
                continue
        try:
            self._drain_outcomes()
            self._renew_active(now)
            if self._active is None:
                self._schedule_one()
        except Exception:
            pass
        for game in games:
            if game.removing:continue
            if game.dirty_at is not None and now >= game.dirty_at:
                try:
                    self._publish_ready(game)
                    game.dirty_at = None
                except Exception:
                    game.dirty_at = time.monotonic() + 1.0
            if game.compat_pending and not game.paused:
                try:
                    self._publish_compatibility(game, limit=16)
                except Exception:
                    game.compat_pending = True

    def _schedule_one(self):
        with self._lock:
            games = list(self._games.values())
            if not games:
                return
            # While any game is in the foreground, keep background games from
            # consuming GPU/CPU time. Only that player's own small live jobs may
            # run, and only after _can_admit_live approves fresh performance data.
            active_players = [game for game in games if game.player_active]
            if active_players:
                games = active_players
            start = self._cursor % len(games)
            ordered = games[start:] + games[:start]
            self._cursor = (start + 1) % len(games)
        for game in ordered:
            if game.paused or game.removing:
                continue
            if not game.store.has_waiting(game.recipe.key):
                if game.resource_reason:
                    game.resource_reason='';self._notify(game.workspace.name)
                continue
            if game.player_active and not self._can_admit_live(game):
                continue
            limit = 1
            pixel_budget = self._batch_pixels
            try:
                backend = self._backend_factory(game.recipe)
                if callable(getattr(backend, "enhance_many", None)):
                    budget=backend.batch_limits() if callable(getattr(backend,'batch_limits',None)) else None
                    if budget is not None and budget.reason:
                        if game.resource_reason!=budget.reason:
                            game.resource_reason=budget.reason;self._notify(game.workspace.name)
                        continue
                    if not game.player_active and game.recipe.key not in self._batch_disabled:
                        limit = self._batch_size
                        if budget is not None:
                            limit=min(limit,budget.max_images)
                            pixel_budget=min(pixel_budget,budget.max_pixels)
            except Exception:
                # Let the normal single-job path record a useful backend error.
                pass
            if not game.player_active:game.batch_limit=limit
            try:
                leases = game.store.claim_batch(self._owner, lease_seconds=self._lease_seconds,
                    recipe_key=game.recipe.key, max_count=limit, max_pixels=pixel_budget)
            except Exception:
                continue
            items = []
            for lease in leases:
                try:
                    source = game.store.get_source(lease.source_id)
                    recipe_json = game.store.recipe_json(lease.recipe_key)
                    if source is None or recipe_json is None:
                        raise ValueError("Job source or recipe is missing")
                    if game.player_active and source.width * source.height > 65_536:
                        game.store.defer(lease, retry_at=time.time() + 30.0,
                                         reason="Deferred during play: source is larger than the live-work limit")
                        self._set_live_reason(game, "Large images are queued until the player closes")
                        continue
                    items.append(_Work(game, lease, source, Recipe.from_json(recipe_json)))
                except (KeyError, ValueError, RuntimeError) as error:
                    game.store.mark_failed(lease, str(error), retry_at=None)
            if not items:
                continue
            batch = _Batch(tuple(items))
            try:
                self._work.put_nowait(batch)
            except queue.Full:
                for work in items:
                    game.store.mark_failed(work.lease, "Worker queue is busy", retry_at=time.time() + 1.0)
                continue
            self._active = batch
            game.resource_reason=''
            self._lease_renew_at = time.monotonic() + self._lease_seconds / 3
            if game.player_active:
                game.last_live_job_at = time.monotonic()
                game.live_jobs_started += 1
                self._set_live_reason(game, "Preparing one small image; further work waits for fresh performance data")
            self._notify(game.workspace.name)
            return

    def _can_admit_live(self, game: _Game) -> bool:
        now = time.monotonic()
        if not game.live_enabled:
            self._set_live_reason(game, "Live image work paused by the user")
            return False
        if self._active is not None:
            self._set_live_reason(game, "Waiting for the current image job to finish")
            return False
        if game.metrics_path is None:
            self._set_live_reason(game, "Waiting for player performance data")
            return False
        if now - game.metric_checked_at >= 0.5:
            game.metric_checked_at = now
            try:
                report = json.loads(game.metrics_path.read_text(encoding="utf-8"))
                updated = float(report.get("updated", 0.0))
                values = {key: float(report.get(key, 0.0)) for key in
                          ("fps", "frame_p95_ms", "input_queue_p95_ms")}
                if any(not math.isfinite(value) or value < 0 for value in values.values()):
                    raise ValueError("non-finite player metrics")
                game.metric_updated = updated
                game.metric_values = values
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                self._set_live_reason(game, "Waiting for fresh player performance data")
                return False
        report = game.metric_values or {}
        age = time.time() - game.metric_updated
        if age < -2.0 or age > 4.0 or report.get("fps", 0.0) <= 0 or report.get("frame_p95_ms", 0.0) <= 0:
            self._set_live_reason(game, "Performance data is stale; image work is deferred")
            return False
        if game.metric_updated != game.metric_sampled and self._active is None:
            game.metric_sampled = game.metric_updated
            if len(game.baseline_frames) < 4:
                game.baseline_frames.append(report["frame_p95_ms"])
                game.baseline_inputs.append(report["input_queue_p95_ms"])
                game.baseline_fps.append(report["fps"])
        if len(game.baseline_frames) < 4:
            self._set_live_reason(game, "Measuring game performance before live image work")
            return False
        baseline_frame = self._median(game.baseline_frames)
        baseline_input = self._median(game.baseline_inputs)
        baseline_fps = self._median(game.baseline_fps)
        if (report["frame_p95_ms"] > max(60.0, baseline_frame * 1.8 + 10.0) or
                report["input_queue_p95_ms"] > max(25.0, baseline_input * 2.0 + 10.0) or
                report["fps"] < max(10.0, baseline_fps * 0.60)):
            self._set_live_reason(game, "Frame or input latency is high; image work is deferred")
            return False
        if now - game.last_live_job_at < 8.0:
            cooldown = max(8.0, min(30.0, game.last_live_job_seconds * 2.0))
            if now - game.last_live_job_at < cooldown:
                self._set_live_reason(game, "Live image-work cooldown; saved artwork remains active")
                return False
        self._set_live_reason(game, "Performance headroom available for one small image")
        return True

    @staticmethod
    def _median(values: list[float]) -> float:
        ordered = sorted(values)
        middle = len(ordered) // 2
        if len(ordered) % 2:
            return ordered[middle]
        return (ordered[middle - 1] + ordered[middle]) / 2.0

    def _set_live_reason(self, game: _Game, reason: str):
        if game.live_reason == reason:
            return
        game.live_reason = reason
        self._notify(game.workspace.name)

    def _renew_active(self, now: float):
        batch = self._active
        if batch is None or now < self._lease_renew_at:
            return
        items = []
        retry = False
        for work in batch.items:
            try:
                renewed = work.game.store.renew(work.lease, lease_seconds=self._lease_seconds)
            except Exception:
                renewed = None
                retry = True
            # Even a lost lease must occupy the GPU slot until its dispatched
            # work completes. Token checks prevent its stale outcome committing.
            items.append(_Work(work.game, renewed or work.lease, work.source, work.recipe))
        self._active = _Batch(tuple(items))
        self._lease_renew_at = now + (1.0 if retry else self._lease_seconds / 3)

    def _worker_loop(self):
        while not self._stop.is_set():
            try:
                batch = self._work.get(timeout=0.2)
            except queue.Empty:
                continue
            if batch is None:
                return
            if len(batch.items) > 1:
                started = time.monotonic()
                try:
                    outputs = self._execute_batch(batch.items)
                except Exception as error:
                    game = batch.items[0].game
                    with self._lock:
                        self._batch_disabled.add(batch.items[0].recipe.key)
                        game.batch_fallbacks += 1
                    try:
                        log = game.workspace / "logs" / "enhancement-batch.log"
                        log.parent.mkdir(parents=True, exist_ok=True)
                        with log.open("a", encoding="utf-8") as stream:
                            stream.write(f"{time.time():.3f}: Batch failed; retrying separately: {type(error).__name__}: {error}\n")
                    except OSError:
                        pass
                    elapsed = time.monotonic() - started
                    for work in batch.items:
                        self._outcomes.put(_Outcome(work, None,
                            f"Batch failed; retrying separately: {type(error).__name__}: {error}",
                            elapsed, retry_single=True))
                    continue
                else:
                    elapsed = time.monotonic() - started
                    for work, output in zip(batch.items, outputs):
                        self._outcomes.put(_Outcome(work, output, None, elapsed))
                    continue
            for work in batch.items:
                self._outcomes.put(self._run_single(work))

    def _run_single(self, work: _Work) -> _Outcome:
        started = time.monotonic()
        try:
            output = self._execute(work)
            return _Outcome(work, output, None, time.monotonic() - started)
        except Exception as error:
            return _Outcome(work, None, f"{type(error).__name__}: {error}",
                            time.monotonic() - started,resource_defer=isinstance(error,ResourcePressure))

    def _execute(self, work: _Work) -> str:
        store, source, recipe = work.game.store, work.source, work.recipe
        source_path = store.resolve_path(source.relative_path)
        image = self._read_source(source_path, source.source_id)
        if image.size != (source.width, source.height):
            raise ValueError("Source dimensions changed after registration")
        backend = self._backend_factory(recipe)
        temporary_root = work.game.workspace / ".runtime" / "tmp"
        temporary_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="job-", dir=temporary_root) as workdir:
            result = backend.enhance(image, recipe, Path(workdir)).convert("RGBA")
            self._publish_execution_report(work.game.workspace,Path(workdir))
            return self._save_result(work, result)

    def _execute_batch(self, items: tuple[_Work, ...]) -> list[str]:
        first = items[0]
        images = []
        for work in items:
            if work.game is not first.game or work.recipe != first.recipe:
                raise ValueError("A model batch must share one workspace and recipe")
            image = self._read_source(work.game.store.resolve_path(work.source.relative_path), work.source.source_id)
            if image.size != (work.source.width, work.source.height):
                raise ValueError("Source dimensions changed after registration")
            images.append(image)
        backend = self._backend_factory(first.recipe)
        temporary_root = first.game.workspace / ".runtime" / "tmp"
        temporary_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="batch-", dir=temporary_root) as workdir:
            results = list(backend.enhance_many(images, first.recipe, Path(workdir)))
            if len(results) != len(items):
                raise ValueError("Backend returned an unexpected batch size")
            self._publish_execution_report(first.game.workspace,Path(workdir))
            return [self._save_result(work, result.convert("RGBA")) for work, result in zip(items, results)]

    @staticmethod
    def _publish_execution_report(workspace: Path,workdir: Path):
        source=workdir/'logs/last-conversion-gpu.json'
        try:
            if not source.is_file() or source.stat().st_size>32_768:return
            report=json.loads(source.read_text(encoding='utf-8'))
            if not isinstance(report,dict):return
            destination=workspace/'logs/last-conversion-gpu.json'
            destination.parent.mkdir(parents=True,exist_ok=True)
            temporary=destination.with_name('conversion-'+uuid.uuid4().hex+'.tmp')
            try:
                temporary.write_text(json.dumps(report,indent=2),encoding='utf-8')
                os.replace(temporary,destination)
            finally:temporary.unlink(missing_ok=True)
        except (OSError,ValueError):pass

    @staticmethod
    def _save_result(work: _Work, result: Image.Image) -> str:
        store, source, recipe = work.game.store, work.source, work.recipe
        expected = (source.width * recipe.scale, source.height * recipe.scale)
        if result.size != expected:
            raise ValueError(f"Backend returned {result.size}; expected {expected}")
        relative = f"textures-cache/{recipe.key}/{source.source_id}.png"
        target = store.resolve_path(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + "." + work.lease.token + ".tmp")
        try:
            result.save(temporary, format="PNG")
            with Image.open(temporary) as checked:
                checked.verify()
            with Image.open(temporary) as checked:
                if checked.size != expected:
                    raise ValueError("Encoded enhancement has unexpected dimensions")
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        return relative

    def _drain_outcomes(self):
        changed = set()
        while True:
            try:
                outcome = self._outcomes.get_nowait()
            except queue.Empty:
                break
            work, game = outcome.work, outcome.work.game
            try:
                if outcome.resource_defer:
                    game.store.defer(work.lease,retry_at=time.time()+15,
                                     reason=outcome.error or 'Waiting for memory')
                    game.resource_reason=outcome.error or 'Waiting for memory'
                elif outcome.retry_single:
                    # Re-enter normal admission: a player may have opened or the
                    # user may have paused while the batch was still running.
                    game.store.reschedule(work.lease, outcome.error or "Retrying separately")
                elif outcome.error is not None:
                    retry_at = time.time() + min(300, 10 * (2 ** min(work.lease.attempts - 1, 4)))
                    if work.lease.attempts >= 3:
                        retry_at = None
                    game.store.mark_failed(work.lease, outcome.error, retry_at=retry_at)
                elif outcome.output is not None and game.store.mark_ready(work.lease, outcome.output):
                    game.dirty_at = time.monotonic() + 0.5
                    game.compat_pending = True
            except Exception:
                pass
            if game.player_active:
                game.last_live_job_seconds = outcome.elapsed
            if self._active is not None:
                remaining = tuple(item for item in self._active.items if item.lease.token != work.lease.token)
                self._active = _Batch(remaining) if remaining else None
            changed.add(game.workspace.name)
        for game_id in changed:
            self._notify(game_id)

    def _publish_compatibility(self, game: _Game, *, limit: int):
        """Maintain the current player's legacy texture folder outside active play."""
        jobs = game.store.list_ready(game.recipe.key)
        marker = game.workspace / ".runtime" / "compatibility.json"
        if game.compat_recipe_key != game.recipe.key or game.compat_sources is None:
            game.compat_recipe_key, game.compat_sources = self._read_compatibility_state(
                game.workspace, game.recipe.key)
        already = game.compat_sources
        pending = []
        for job in jobs:
            if not job.relative_output:
                continue
            source = game.store.get_source(job.source_id)
            if source is None:
                continue
            directory = "textures" if game.recipe.algorithm == "scale2x-rgba" else "textures-ai"
            target = game.store.resolve_path(f"{directory}/{job.source_id}.png")
            if (job.source_id in already and target.is_file()) or (
                    game.workspace / "textures-ui" / f"{job.source_id}.png").is_file():
                already.add(job.source_id)
                continue
            pending.append((job, target))
        for job, target in pending[:limit]:
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(target.name + "." + uuid.uuid4().hex + ".tmp")
            try:
                shutil.copyfile(game.store.resolve_path(job.relative_output), temporary)
                with self._compat_commit_lock:
                    if game.paused:
                        game.compat_pending = True
                        return
                    os.replace(temporary, target)
                    already.add(job.source_id)
            finally:
                temporary.unlink(missing_ok=True)
        remaining = [job for job, _ in pending[limit:]]
        if remaining:
            game.compat_pending = True
            return
        ready_ids = {job.source_id for job in jobs if job.relative_output}
        game.compat_pending = not ready_ids.issubset(already)
        if not game.compat_pending:
            marker.parent.mkdir(parents=True, exist_ok=True)
            temporary = marker.with_name(marker.name + "." + uuid.uuid4().hex + ".tmp")
            payload = {"schema": 1, "recipe_key": game.recipe.key,
                       "sources": sorted(ready_ids)}
            try:
                temporary.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")),
                                     encoding="utf-8")
                os.replace(temporary, marker)
                game.compat_recipe_key = game.recipe.key
                game.compat_sources = set(ready_ids)
            finally:
                temporary.unlink(missing_ok=True)

    @staticmethod
    def _read_compatibility_state(workspace: Path, recipe_key: str) -> tuple[str, set[str]]:
        marker = workspace / ".runtime" / "compatibility.json"
        try:
            saved = json.loads(marker.read_text(encoding="utf-8"))
            if saved.get("recipe_key") == recipe_key and isinstance(saved.get("sources"), list):
                return recipe_key, {value for value in saved["sources"] if isinstance(value, str)}
        except (OSError, ValueError, TypeError):
            pass
        return "", set()

    def _publish_ready(self, game: _Game):
        valid_sources = []
        for job in game.store.list_ready(game.recipe.key):
            if not job.relative_output:
                game.store.invalidate_ready(job.source_id, job.recipe_key)
                continue
            source = game.store.get_source(job.source_id)
            if source is None:
                game.store.invalidate_ready(job.source_id, job.recipe_key)
                continue
            path = game.store.resolve_path(job.relative_output)
            try:
                with Image.open(path) as image:
                    image.verify()
                with Image.open(path) as image:
                    is_valid = image.size == (source.width * game.recipe.scale,
                                              source.height * game.recipe.scale)
            except (OSError, ValueError):
                is_valid = False
            if is_valid:
                valid_sources.append(job.source_id)
            else:
                game.store.invalidate_ready(job.source_id, job.recipe_key)
        ready_dir = game.workspace / ".runtime" / "ready"
        ready_dir.mkdir(parents=True, exist_ok=True)
        manifest = ready_dir / (game.recipe.key + ".json")
        try:
            previous = json.loads(manifest.read_text(encoding="utf-8"))
            game.generation = max(game.generation, int(previous.get("generation", 0)))
        except (OSError, ValueError, TypeError):
            pass
        game.generation += 1
        payload = {"schema": 1, "generation": game.generation,
                   "recipe_key": game.recipe.key, "scale": game.recipe.scale,
                   "sources": sorted(valid_sources)}
        temporary = manifest.with_name(manifest.name + "." + uuid.uuid4().hex + ".tmp")
        try:
            temporary.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")),
                                 encoding="utf-8")
            os.replace(temporary, manifest)
        finally:
            temporary.unlink(missing_ok=True)
        self._notify(game.workspace.name)

    def close(self, timeout: float = 1.0):
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._stop.set()
        try:
            self._work.put_nowait(None)
        except queue.Full:
            pass
        for thread in (self._coordinator, self._worker):
            if thread is not None and thread is not threading.current_thread():
                thread.join(max(0.0, timeout))
        if self._worker is None or not self._worker.is_alive():
            self._drain_outcomes()
