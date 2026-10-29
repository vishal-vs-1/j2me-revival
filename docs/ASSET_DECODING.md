# Asset discovery and decoder contracts

Import and play use the same generic asset pipeline. Import reads standard image resources, embedded PNGs, and structurally validated containers. At runtime, shared emulator hooks observe decoded immutable images, stable offscreen snapshots, and sampled raw RGB blocks. The game continues to run its own decoder. No title name, archive hash, class name, or codec fingerprint selects an enhancement path.

| Responsibility | Implementation | Contract |
|---|---|---|
| Select common import readers | `asset_decoding.DecoderRegistry` | Readers accept recognized, bounded formats; unknown blocks stay opaque. No game code executes during import. |
| Normalize and persist source images | `AssetSink`, `runtime_assets` | Pixel identity, dimensions, alpha policy, and provenance are shared by import and runtime discovery. Archive paths never become output paths. |
| Read ordinary images | `StandardImages` | Pillow decodes supported images without executing game code. |
| Extract embedded PNGs | `EmbeddedImages` | Complete chunk boundaries and CRCs must validate. |
| Unpack a recognized container | `gameloft_resources` | Index tables, bounds, and decompressed output are validated and limited. Unknown payloads remain untouched. |
| Enhance prepared or observed images | `AssetService` and backend implementations | Work is deduplicated by source identity and recipe, persists across launches, and runs outside the game/render thread. |
| Display cached artwork | `TextureRepository`, `GpuRenderer`, `Enhancement` | Async cache lookup; updates are staged at frame boundaries and rejected when source revision or recipe is stale. |

## Persistence

`asset-decoding.json` records the JAR hash, pipeline version, registered common readers, recognized stages, and unresolved resource information. `catalogue.json` records normalized sources and their provenance. `original-assets/` contains source PNGs; `textures-cache/` and the ready manifest contain validated recipe-specific outputs. Legacy source images remain valid inputs even when they were produced by an older extractor.

Source preparation is reused only when the JAR, reader versions, and indexed files still match. Enhancement recipe changes reuse known source pixels and create separate cached variants. Historical cache files with unknown provenance remain legacy variants; they are not silently relabeled as results of a new recipe.

## Coverage and extension

This pipeline recognizes common stored image formats and observes images after a game has decoded them. It cannot infer every private sprite layout from arbitrary bytes. Packed binary data may represent images, palettes, maps, sound, or other structures; unknown data is left for the game’s normal runtime logic. Continuously changing screen buffers remain on the fast render path, and unseen game states are not counted as prepared assets.

Add new shared readers only for formats validated by structure and bounds. Emit normalized images through `AssetSink`; preserve animation and frame provenance without changing game coordinates. Keep format support independent from the upscaler, renderer, UI, and input handling.
