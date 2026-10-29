import json
from pathlib import Path
import tempfile
import threading
import time

import pytest
from PIL import Image

from runtime_assets.contracts import Recipe, SourceRecord, image_source_id
from runtime_assets.service import AssetService
from runtime_assets.store import AssetStore


@pytest.fixture
def tmp_path():
    parent = Path(__file__).resolve().parents[1] / "build" / "test-runtime-assets"
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="service-", dir=parent) as directory:
        yield Path(directory)


def _recipe():
    return Recipe(1, "test-scale", "fake-v1", "", 2,
                  "preserve", "edge-repeat", {"filter": "nearest"})


def _source(workspace: Path, folder="original-assets", color=(40, 90, 150, 255)):
    path = workspace / folder / "source.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGBA", (3, 2), color)
    image.save(path)
    source_id = image_source_id(image)
    target = path.with_name(source_id + ".png")
    path.rename(target)
    return image, SourceRecord(source_id, image.width, image.height,
                               target.relative_to(workspace).as_posix(), "imported")


def _wait_until(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


class FakeBackend:
    algorithm = "test-scale"

    def __init__(self, calls, *, started=None, release=None):
        self.calls = calls
        self.started = started
        self.release = release

    def enhance(self, source, recipe, workdir):
        self.calls.append(source.size)
        if self.started is not None:
            self.started.set()
        if self.release is not None:
            self.release.wait(5)
        return source.resize((source.width * recipe.scale, source.height * recipe.scale),
                             Image.Resampling.NEAREST)


class BatchBackend(FakeBackend):
    def __init__(self,calls,*,fail=False,started=None,release=None):
        super().__init__(calls,started=started,release=release)
        self.batches=[]
        self.fail=fail

    def enhance_many(self,sources,recipe,workdir):
        self.batches.append(len(sources))
        if self.started is not None:self.started.set()
        if self.release is not None:self.release.wait(5)
        if self.fail:raise RuntimeError('simulated batch failure')
        return [source.resize((source.width*recipe.scale,source.height*recipe.scale),
                              Image.Resampling.NEAREST) for source in sources]


def _several_sources(workspace,count=5):
    return [_source(workspace,color=(index*19,90,150,255))[1] for index in range(count)]


def test_idle_batch_publishes_individual_cache_entries_and_restart_reuses_them(tmp_path):
    workspace=tmp_path/'batch-game';workspace.mkdir()
    sources=_several_sources(workspace)
    recipe=_recipe();backend=BatchBackend([])
    service=AssetService(lambda selected:backend,poll_seconds=0.02)
    try:
        service.register_game(workspace,recipe,game={'id':workspace.name},paused=True)
        service.resume(workspace.name)
        assert _wait_until(lambda:service.stats(workspace.name)['READY']==len(sources))
        assert backend.batches==[5] and backend.calls==[]
        for source in sources:
            output=workspace/'textures-cache'/recipe.key/(source.source_id+'.png')
            with Image.open(output) as image:assert image.size==(source.width*2,source.height*2)
    finally:service.close()
    restored=BatchBackend([])
    service=AssetService(lambda selected:restored,poll_seconds=0.02)
    try:
        service.register_game(workspace,recipe,game={'id':workspace.name})
        assert service.stats(workspace.name)['READY']==len(sources)
        assert restored.batches==[] and restored.calls==[]
    finally:service.close()


def test_batch_keeps_execution_report_after_temporary_inputs_are_removed(tmp_path):
    workspace=tmp_path/'reported-batch';workspace.mkdir()
    _several_sources(workspace)
    class ReportingBackend(BatchBackend):
        def enhance_many(self,sources,recipe,workdir):
            report=workdir/'logs/last-conversion-gpu.json'
            report.parent.mkdir(parents=True)
            report.write_text(json.dumps({'images':len(sources),'processing_threads':2}))
            return super().enhance_many(sources,recipe,workdir)
    service=AssetService(lambda selected:ReportingBackend([]),poll_seconds=0.02)
    try:
        service.register_game(workspace,_recipe(),game={'id':workspace.name})
        assert _wait_until(lambda:service.stats(workspace.name)['READY']==5)
        report=json.loads((workspace/'logs/last-conversion-gpu.json').read_text())
        assert report=={'images':5,'processing_threads':2}
        assert not list((workspace/'.runtime/tmp').iterdir())
    finally:service.close()


def test_live_work_never_uses_background_batch_size(tmp_path):
    workspace=tmp_path/'live-batch-game';workspace.mkdir()
    sources=_several_sources(workspace)
    backend=BatchBackend([]);recipe=_recipe()
    service=AssetService(lambda selected:backend,poll_seconds=0.02)
    try:
        service.register_game(workspace,recipe,game={'id':workspace.name},paused=True)
        service._can_admit_live=lambda game:True
        service.set_player_state(workspace.name,True)
        assert _wait_until(lambda:service.stats(workspace.name)['READY']==len(sources))
        assert backend.batches==[] and len(backend.calls)==5
    finally:service.close()


def test_failed_batch_retries_separately_without_losing_jobs(tmp_path):
    workspace=tmp_path/'failed-batch-game';workspace.mkdir()
    sources=_several_sources(workspace)
    backend=BatchBackend([],fail=True);recipe=_recipe()
    service=AssetService(lambda selected:backend,poll_seconds=0.02)
    try:
        service.register_game(workspace,recipe,game={'id':workspace.name},paused=True)
        service.resume(workspace.name)
        assert _wait_until(lambda:service.stats(workspace.name)['READY']==len(sources))
        assert backend.batches==[5] and len(backend.calls)==5
        assert service.stats(workspace.name)['batch_fallbacks']==1
        assert service.stats(workspace.name)['FAILED']==0
        assert (workspace/'logs/enhancement-batch.log').is_file()
    finally:service.close()


def test_batch_failure_retries_wait_for_player_admission(tmp_path):
    workspace=tmp_path/'batch-player-transition';workspace.mkdir()
    _several_sources(workspace)
    started,release=threading.Event(),threading.Event()
    backend=BatchBackend([],fail=True,started=started,release=release);recipe=_recipe()
    service=AssetService(lambda selected:backend,poll_seconds=0.02)
    try:
        service.register_game(workspace,recipe,game={'id':workspace.name},paused=True)
        service.resume(workspace.name)
        assert started.wait(2)
        service._can_admit_live=lambda game:False
        service.set_player_state(workspace.name,True)
        release.set()
        assert _wait_until(lambda:service.stats(workspace.name)['QUEUED']==5)
        assert backend.calls==[] and service.stats(workspace.name)['RUNNING']==0
        service.set_player_state(workspace.name,False)
        assert _wait_until(lambda:service.stats(workspace.name)['READY']==5)
    finally:
        release.set();service.close()


def test_resource_policy_defers_without_claiming_and_then_uses_its_batch_limit(tmp_path):
    from runtime_assets.resources import PreparationBudget
    workspace=tmp_path/'resource-policy-game';workspace.mkdir()
    _several_sources(workspace)
    backend=BatchBackend([]);recipe=_recipe()
    chosen=[PreparationBudget(1,1024,reason='Waiting for memory')]
    backend.batch_limits=lambda:chosen[0]
    service=AssetService(lambda selected:backend,poll_seconds=0.02)
    try:
        service.register_game(workspace,recipe,game={'id':workspace.name})
        assert _wait_until(lambda:service.stats(workspace.name)['resource_reason']=='Waiting for memory')
        assert service.stats(workspace.name)['QUEUED']==5
        assert backend.batches==[] and backend.calls==[]
        chosen[0]=PreparationBudget(2,1024)
        assert _wait_until(lambda:service.stats(workspace.name)['READY']==5)
        assert backend.batches==[2,2] and len(backend.calls)==1
        assert not service.stats(workspace.name)['resource_reason']
    finally:service.close()


def test_memory_limited_image_is_deferred_without_becoming_a_failed_source(tmp_path):
    from runtime_assets.resources import ResourcePressure
    workspace=tmp_path/'resource-deferred';workspace.mkdir()
    _,source=_source(workspace)
    class LimitedBackend(FakeBackend):
        def enhance(self,*args):raise ResourcePressure('Waiting for CPU memory')
    service=AssetService(lambda selected:LimitedBackend([]),poll_seconds=0.02)
    try:
        service.register_game(workspace,_recipe(),game={'id':workspace.name})
        assert _wait_until(lambda:service.stats(workspace.name)['DEFERRED']==1)
        assert service.stats(workspace.name)['FAILED']==0
        assert service._game(workspace.name).store.get_job(source.source_id,_recipe().key).error=='ResourcePressure: Waiting for CPU memory'
    finally:service.close()


def test_lease_renewal_covers_every_image_in_a_batch(tmp_path,monkeypatch):
    workspace=tmp_path/'renew-batch-game';workspace.mkdir()
    _several_sources(workspace)
    started,release=threading.Event(),threading.Event()
    backend=BatchBackend([],started=started,release=release);recipe=_recipe()
    service=AssetService(lambda selected:backend,poll_seconds=0.02)
    try:
        service.register_game(workspace,recipe,game={'id':workspace.name},paused=True)
        service.resume(workspace.name)
        assert started.wait(2)
        store=service._game(workspace.name).store
        original=store.renew;tokens=[]
        def record(lease,**kwargs):
            tokens.append(lease.token)
            return original(lease,**kwargs)
        monkeypatch.setattr(store,'renew',record)
        service._renew_active(time.monotonic()+100)
        assert len(set(tokens))==5
        assert service.stats(workspace.name)['RUNNING']==5
    finally:
        release.set();service.close()


def test_completed_batch_is_committed_when_coordinator_stops(tmp_path):
    workspace=tmp_path/'closing-batch-game';workspace.mkdir()
    _several_sources(workspace)
    started,release=threading.Event(),threading.Event()
    backend=BatchBackend([],started=started,release=release);recipe=_recipe()
    service=AssetService(lambda selected:backend,poll_seconds=0.02)
    timer=None
    try:
        service.register_game(workspace,recipe,game={'id':workspace.name},paused=True)
        service.resume(workspace.name)
        assert started.wait(2)
        timer=threading.Timer(0.1,release.set);timer.start()
        service.close(timeout=2)
        assert AssetStore(workspace).counts(recipe.key)['READY']==5
    finally:
        release.set()
        if timer is not None:timer.join()
        service.close()


def test_unregister_waits_for_current_batch_and_blocks_new_work(tmp_path):
    workspace=tmp_path/'remove-batch-game';workspace.mkdir()
    _several_sources(workspace)
    started,release=threading.Event(),threading.Event()
    backend=BatchBackend([],started=started,release=release)
    service=AssetService(lambda selected:backend,poll_seconds=0.02,batch_size=2)
    finished=threading.Event();errors=[]
    def unregister():
        try:service.unregister_game(workspace.name,timeout=5)
        except Exception as error:errors.append(error)
        finally:finished.set()
    remover=None
    try:
        service.register_game(workspace,_recipe(),game={'id':workspace.name})
        assert started.wait(3)
        remover=threading.Thread(target=unregister);remover.start()
        assert _wait_until(lambda:service._game(workspace.name).removing)
        service.resume_all()  # Periodic UI updates must not re-admit a deleting game.
        assert not finished.is_set()
        release.set()
        assert finished.wait(5) and not errors
        with pytest.raises(KeyError):service.stats(workspace.name)
        with service._coordinator_gate:service._coordinate_once()
        assert backend.batches==[2] and backend.calls==[]
        assert service._active is None
    finally:
        release.set()
        if remover is not None:remover.join(5)
        service.close()


def test_unregister_timeout_keeps_game_registered_and_recoverable(tmp_path):
    workspace=tmp_path/'remove-timeout-game';workspace.mkdir()
    _several_sources(workspace)
    started,release=threading.Event(),threading.Event()
    backend=BatchBackend([],started=started,release=release)
    service=AssetService(lambda selected:backend,poll_seconds=0.02)
    try:
        service.register_game(workspace,_recipe(),game={'id':workspace.name})
        assert started.wait(3)
        with pytest.raises(TimeoutError):service.unregister_game(workspace.name,timeout=0)
        assert not service._game(workspace.name).removing
        assert not service.stats(workspace.name)['paused']
        release.set()
        assert _wait_until(lambda:service.stats(workspace.name)['READY']==5)
    finally:release.set();service.close()


def test_unregister_refuses_an_active_player_without_changing_its_state(tmp_path):
    workspace=tmp_path/'remove-playing-game';workspace.mkdir()
    service=AssetService(lambda selected:FakeBackend([]),poll_seconds=0.02)
    try:
        service.register_game(workspace,_recipe(),game={'id':workspace.name},paused=True)
        service.set_player_state(workspace.name,True)
        with pytest.raises(RuntimeError,match='Close the game'):service.unregister_game(workspace.name)
        assert service.stats(workspace.name)['player_active']
        assert not service._game(workspace.name).removing
    finally:service.close()


def test_slow_backend_does_not_block_registering_another_game(tmp_path):
    calls = []
    started, release = threading.Event(), threading.Event()
    service = AssetService(lambda recipe: FakeBackend(calls, started=started, release=release),
                           poll_seconds=0.02, lease_seconds=15)
    recipe = _recipe()
    try:
        first = tmp_path / "game-one"
        first.mkdir()
        service.register_game(first, recipe, game={"id": first.name})
        _, first_source = _source(first)
        assert service.register_imported_sources(first, [first_source]) == 1
        assert started.wait(2)

        second = tmp_path / "game-two"
        second.mkdir()
        before = time.monotonic()
        service.register_game(second, recipe, game={"id": second.name})
        _, second_source = _source(second)
        assert service.register_imported_sources(second, [second_source]) == 1
        assert time.monotonic() - before < 0.5

        release.set()
        assert _wait_until(lambda: service.stats(first.name)["READY"] == 1 and
                           service.stats(second.name)["READY"] == 1)
        assert len(calls) == 2
    finally:
        release.set()
        service.close()


def test_valid_cache_hit_publishes_manifest_without_running_backend(tmp_path):
    calls = []
    workspace = tmp_path / "cached-game"
    workspace.mkdir()
    image, source = _source(workspace)
    recipe = _recipe()
    store = AssetStore(workspace)
    store.register_recipe(recipe)
    store.register_source(source)
    assert store.enqueue(source.source_id, recipe.key)
    lease = store.claim("test-cache-worker")
    output = f"textures-cache/{recipe.key}/{source.source_id}.png"
    target = store.resolve_path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    image.resize((image.width * 2, image.height * 2)).save(target)
    assert store.mark_ready(lease, output)

    service = AssetService(lambda selected: FakeBackend(calls), poll_seconds=0.02)
    try:
        service.register_game(workspace, recipe, game={"id": workspace.name}, paused=True)
        manifest = workspace / ".runtime" / "ready" / f"{recipe.key}.json"
        assert _wait_until(manifest.is_file)
        document = json.loads(manifest.read_text(encoding="utf-8"))
        assert document["sources"] == [source.source_id]
        assert service.stats(workspace.name)["READY"] == 1
        assert calls == []
    finally:
        service.close()


def test_event_ingest_validates_hash_deduplicates_and_acknowledges(tmp_path):
    workspace = tmp_path / "event-game"
    workspace.mkdir()
    _, source = _source(workspace, folder="captures")
    recipe = _recipe()
    service = AssetService(lambda selected: FakeBackend([]), poll_seconds=0.02)
    event_dir = workspace / ".runtime" / "events"
    event_dir.mkdir(parents=True)
    event_path = event_dir / "session-1.json"
    event_path.write_text(json.dumps({
        "schema": 1,
        "event_id": "session-1-1",
        "type": "capture-ready",
        "source_id": source.source_id,
        "width": source.width,
        "height": source.height,
        "origin": "RGB",
        "source_path": source.relative_path,
    }), encoding="utf-8")
    try:
        service.register_game(workspace, recipe, game={"id": workspace.name}, paused=True)
        assert service.reconcile(workspace.name) == 1
        assert not event_path.exists()
        assert service.stats(workspace.name)["QUEUED"] == 1
        assert service.reconcile(workspace.name) == 0
        assert service.stats(workspace.name)["QUEUED"] == 1
    finally:
        service.close()


def test_live_admission_waits_for_baseline_freshness_and_frame_headroom(tmp_path):
    workspace = tmp_path / "live-metrics-game"
    workspace.mkdir()
    metrics = workspace / "player.stats.json"
    service = AssetService(lambda selected: FakeBackend([]), poll_seconds=0.02)
    try:
        service.register_game(workspace, _recipe(), game={"id": workspace.name}, paused=True)
        service.set_player_state(workspace.name, True, metrics)
        game = service._game(workspace.name)
        # Keep the background scheduler out of this deterministic policy check.
        with service._lock:
            game.paused = True
        for index in range(4):
            metrics.write_text(json.dumps({"updated": time.time(), "fps": 60.0,
                                           "frame_p95_ms": 16.0, "input_queue_p95_ms": 2.0}),
                               encoding="utf-8")
            with service._lock:
                game.metric_checked_at = 0.0
            admitted = service._can_admit_live(game)
            assert admitted is (index == 3)
            time.sleep(0.01)
        assert game.live_reason == "Performance headroom available for one small image"

        metrics.write_text(json.dumps({"updated": time.time(), "fps": 8.0,
                                       "frame_p95_ms": 160.0, "input_queue_p95_ms": 80.0}),
                           encoding="utf-8")
        with service._lock:
            game.metric_checked_at = 0.0
        assert not service._can_admit_live(game)
        assert "latency is high" in game.live_reason

        metrics.write_text(json.dumps({"updated": time.time() - 10.0, "fps": 60.0,
                                       "frame_p95_ms": 16.0, "input_queue_p95_ms": 2.0}),
                           encoding="utf-8")
        with service._lock:
            game.metric_checked_at = 0.0
        assert not service._can_admit_live(game)
        assert "stale" in game.live_reason
    finally:
        service.close()


def test_foreground_player_defers_other_games_background_work(tmp_path):
    calls = []
    service = AssetService(lambda selected: FakeBackend(calls), poll_seconds=1000.0)
    active = tmp_path / "foreground-game"
    background = tmp_path / "background-game"
    active.mkdir()
    background.mkdir()
    recipe = _recipe()
    metrics = active / "player.stats.json"
    try:
        service.register_game(active, recipe, game={"id": active.name}, paused=True)
        service.register_game(background, recipe, game={"id": background.name}, paused=True)
        _, source = _source(background)
        assert service.register_imported_sources(background, [source]) == 1
        service.set_player_state(active.name, True, metrics)
        with service._lock:
            service._game(active.name).paused = False
            service._game(background.name).paused = False
        service._can_admit_live = lambda game: False

        service._schedule_one()

        assert service._active is None
        assert service.stats(background.name)["QUEUED"] == 1
        assert calls == []
    finally:
        service.close()
