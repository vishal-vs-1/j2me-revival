from pathlib import Path
import tempfile

import pytest
from PIL import Image

from engine import image_id
from runtime_assets.backends import PixelBackend
from runtime_assets.contracts import (Recipe, SourceRecord, image_source_id,
                                      ncnn_recipe, pixel_recipe)
from runtime_assets.ingest import LegacyCacheImporter
from runtime_assets.store import AssetStore


@pytest.fixture
def tmp_path():
    """Keep test writes inside the project workspace in restricted environments."""
    parent = Path(__file__).resolve().parents[1] / "build" / "test-runtime-assets"
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="case-", dir=parent) as directory:
        yield Path(directory)


def _image(path: Path, size=(3, 2), color=(30, 80, 140, 255)):
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGBA", size, color)
    image.save(path)
    return image


def _source(image: Image.Image, relative="captures/source.png"):
    return SourceRecord(image_source_id(image), image.width, image.height,
                        relative, "legacy-capture")


def test_recipe_is_canonical_and_deeply_immutable():
    recipe = Recipe(1, "test", "v1", "", 2, "keep", "edge",
                    {"b": [1, {"a": True}], "a": 3})
    equivalent = Recipe(1, "test", "v1", "", 2, "keep", "edge",
                        {"a": 3, "b": [1, {"a": True}]})
    assert recipe.key == equivalent.key
    assert Recipe.from_json(recipe.canonical_json()) == recipe
    with pytest.raises(TypeError):
        recipe.settings["new"] = 1
    with pytest.raises(TypeError):
        recipe.settings["b"][1]["a"] = False


def test_shared_identity_matches_engine_and_ignores_hidden_transparent_rgb():
    first = Image.new("RGBA", (2, 2), (0, 0, 0, 0))
    second = Image.new("RGBA", (2, 2), (200, 80, 10, 0))
    assert image_source_id(first) == image_source_id(second)
    assert image_id(first) == image_source_id(first)
    second.putpixel((1, 1), (200, 80, 10, 255))
    assert image_source_id(first) != image_source_id(second)


def test_job_is_deduplicated_and_expired_lease_is_recovered(tmp_path):
    store = AssetStore(tmp_path)
    image = Image.new("RGBA", (2, 2), (1, 2, 3, 255))
    source = _source(image)
    recipe = pixel_recipe()
    store.register_recipe(recipe)
    store.register_source(source)

    assert store.enqueue(source.source_id, recipe.key, now=100)
    assert not store.enqueue(source.source_id, recipe.key, now=101)
    stale = store.claim("worker-a", now=102, lease_seconds=5)
    assert stale is not None and stale.attempts == 1
    assert store.recover_expired(now=108) == 1

    current = store.claim("worker-b", now=109, lease_seconds=30)
    assert current is not None and current.attempts == 2
    output = tmp_path / "textures" / "source.png"
    _image(output, (8, 8))
    assert not store.mark_ready(stale, "textures/source.png", now=110)
    assert store.mark_ready(current, "textures/source.png", now=110)
    assert store.get_job(source.source_id, recipe.key).state == "READY"


def test_duplicate_pixel_source_keeps_one_durable_job(tmp_path):
    store = AssetStore(tmp_path)
    image = Image.new("RGBA", (2, 2), (1, 2, 3, 255))
    source_id = image_source_id(image)
    store.register_recipe(pixel_recipe())
    store.register_source(SourceRecord(source_id, 2, 2, "original-assets/a.png", "original"))
    store.register_source(SourceRecord(source_id, 2, 2, "captures/b.png", "capture"))
    assert store.enqueue(source_id, pixel_recipe().key)
    assert not store.enqueue(source_id, pixel_recipe().key)
    assert store.pending_count() == 1


def test_batch_claim_respects_budget_without_spending_skipped_attempts(tmp_path):
    store=AssetStore(tmp_path)
    recipe=pixel_recipe()
    store.register_recipe(recipe)
    sources=[]
    for index,size in enumerate(((2,2),(10,10),(2,2))):
        source=_source(Image.new('RGBA',size,(index,50,100,255)),f'original-assets/{index}.png')
        store.register_source(source)
        store.enqueue(source.source_id,recipe.key,now=100+index)
        sources.append(source)
    leases=store.claim_batch('batch-one',now=200,lease_seconds=30,
                            recipe_key=recipe.key,max_count=5,max_pixels=8)
    assert [lease.source_id for lease in leases]==[sources[0].source_id,sources[2].source_id]
    skipped=store.get_job(sources[1].source_id,recipe.key)
    assert skipped.state=='QUEUED' and skipped.attempts==0
    # A large job at the front must run alone instead of being starved by the budget.
    large=store.claim_batch('batch-two',now=201,lease_seconds=30,
                           recipe_key=recipe.key,max_count=5,max_pixels=8)
    assert len(large)==1 and large[0].source_id==sources[1].source_id
    assert len({lease.token for lease in leases+large})==3
    assert store.recover_expired(now=232)==3
    assert store.counts(recipe.key)['QUEUED']==3


def test_parallel_batch_claims_do_not_share_jobs(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    store=AssetStore(tmp_path)
    recipe=pixel_recipe()
    store.register_recipe(recipe)
    for index in range(20):
        source=_source(Image.new('RGBA',(2,2),(index,40,90,255)),f'original-assets/{index}.png')
        store.register_source(source)
        store.enqueue(source.source_id,recipe.key)
    with ThreadPoolExecutor(max_workers=2) as pool:
        batches=list(pool.map(lambda owner:store.claim_batch(owner,recipe_key=recipe.key,max_count=5),
                              ('first-worker','second-worker')))
    assert [len(batch) for batch in batches]==[5,5]
    assert len({lease.source_id for batch in batches for lease in batch})==10
    assert store.counts(recipe.key)['RUNNING']==10
    assert store.counts(recipe.key)['QUEUED']==10


def test_capture_event_and_job_registration_are_atomic_and_idempotent(tmp_path):
    store = AssetStore(tmp_path)
    source = _source(Image.new("RGBA", (2, 2), (3, 4, 5, 255)))
    recipe = pixel_recipe()
    assert store.register_capture_event("capture-1", source, recipe, now=1)
    assert not store.register_capture_event("capture-1", source, recipe, now=2)
    assert store.pending_count() == 1


def test_legacy_import_reuses_cache_only_with_matching_known_recipe(tmp_path):
    workspace = tmp_path / "game-a"
    image = _image(workspace / "original-assets" / "placeholder.png")
    source_id = image_source_id(image)
    original = workspace / "original-assets" / "placeholder.png"
    original.rename(original.with_name(source_id + ".png"))
    _image(workspace / "textures" / (source_id + ".png"), (image.width * 4, image.height * 4))
    store = AssetStore(workspace)
    importer = LegacyCacheImporter(workspace, store)

    report = importer.import_workspace(
        {"id": workspace.name, "backend": "pixel", "recipe": "scale2x-rgba-v1-4x"},
        pixel_recipe(),
    )
    job = store.get_job(source_id, pixel_recipe().key)
    assert report.pixel_cache_reused == 1
    assert report.jobs_queued == 0
    assert job.state == "READY"
    assert job.relative_output == f"textures-cache/{pixel_recipe().key}/{source_id}.png"
    assert (workspace / "textures" / f"{source_id}.png").is_file()


def test_unknown_legacy_cache_is_preserved_but_not_adopted(tmp_path):
    workspace = tmp_path / "game-b"
    image = _image(workspace / "original-assets" / "placeholder.png")
    source_id = image_source_id(image)
    original = workspace / "original-assets" / "placeholder.png"
    original.rename(original.with_name(source_id + ".png"))
    old_texture = workspace / "textures" / (source_id + ".png")
    _image(old_texture, (image.width * 4, image.height * 4))
    store = AssetStore(workspace)
    importer = LegacyCacheImporter(workspace, store)

    report = importer.import_workspace({"id": workspace.name}, pixel_recipe())
    job = store.get_job(source_id, pixel_recipe().key)
    assert report.pixel_cache_reused == 0
    assert report.jobs_queued == 1
    assert job.state == "QUEUED"
    assert old_texture.is_file()
    assert report.legacy_unknown_cache_files == 1


def test_importer_queues_if_known_cache_dimensions_are_wrong(tmp_path):
    workspace = tmp_path / "game-c"
    image = _image(workspace / "original-assets" / "placeholder.png")
    source_id = image_source_id(image)
    original = workspace / "original-assets" / "placeholder.png"
    original.rename(original.with_name(source_id + ".png"))
    old_texture = workspace / "textures" / (source_id + ".png")
    _image(old_texture, (image.width * 2, image.height * 2))
    store = AssetStore(workspace)
    importer = LegacyCacheImporter(workspace, store)

    report = importer.import_workspace(
        {"id": workspace.name, "backend": "pixel", "recipe": "scale2x-rgba-v1-4x"},
        pixel_recipe(),
    )
    assert report.pixel_cache_reused == 0
    assert report.jobs_queued == 1
    assert old_texture.is_file()


def test_legacy_ai_cache_requires_recorded_matching_model_digest(tmp_path):
    workspace = tmp_path / "game-ai"
    image = _image(workspace / "original-assets" / "placeholder.png")
    source_id = image_source_id(image)
    original = workspace / "original-assets" / "placeholder.png"
    original.rename(original.with_name(source_id + ".png"))
    old_texture = workspace / "textures-ai" / (source_id + ".png")
    _image(old_texture, (image.width * 4, image.height * 4))
    model_digest = "a" * 64
    current = ncnn_recipe(model_digest)
    legacy = ncnn_recipe(model_digest, legacy_direct=True)
    store = AssetStore(workspace)
    importer = LegacyCacheImporter(workspace, store)

    metadata = {
        "id": workspace.name,
        "backend": "ai",
        "recipe": "realesrgan-anime-alpha-v1-4x",
        "model_digest": model_digest,
    }
    report = importer.import_workspace(metadata, current, ai_recipe=current)

    assert report.direct_ai_cache_reused == 1
    assert report.jobs_queued == 1
    assert store.get_job(source_id, legacy.key).state == "READY"
    assert store.get_job(source_id, current.key).state == "QUEUED"


def test_legacy_ai_cache_without_model_provenance_is_not_adopted(tmp_path):
    workspace = tmp_path / "game-ai-unknown"
    image = _image(workspace / "original-assets" / "placeholder.png")
    source_id = image_source_id(image)
    original = workspace / "original-assets" / "placeholder.png"
    original.rename(original.with_name(source_id + ".png"))
    old_texture = workspace / "textures-ai" / (source_id + ".png")
    _image(old_texture, (image.width * 4, image.height * 4))
    current = ncnn_recipe("b" * 64)
    store = AssetStore(workspace)
    importer = LegacyCacheImporter(workspace, store)

    report = importer.import_workspace(
        {"id": workspace.name, "backend": "ai", "recipe": "realesrgan-anime-alpha-v1-4x"},
        current,
        ai_recipe=current,
    )

    assert report.direct_ai_cache_reused == 0
    assert report.jobs_queued == 1
    assert report.legacy_unknown_cache_files == 1
    assert store.get_job(source_id, current.key).state == "QUEUED"
    assert old_texture.is_file()


def test_pixel_backend_accepts_only_its_canonical_recipe():
    backend = PixelBackend(lambda image: image.resize((image.width * 4, image.height * 4)))
    source = Image.new("RGBA", (2, 3))
    result = backend.enhance(source, pixel_recipe(), Path("."))
    assert result.size == (8, 12)
    wrong = Recipe(1, "scale2x-rgba", "other-version", "", 4,
                   "transparent-rgb-zero-v1", "edge-repeat-v1", {"passes": 2})
    with pytest.raises(ValueError):
        backend.enhance(source, wrong, Path("."))


@pytest.mark.parametrize("unsafe", ["../outside.png", "C:/outside.png", "textures/../../x.png"])
def test_store_rejects_paths_that_can_escape_workspace(tmp_path, unsafe):
    store = AssetStore(tmp_path)
    with pytest.raises(ValueError):
        store.resolve_path(unsafe)
