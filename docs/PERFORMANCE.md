# Performance notes

Artwork preparation and game rendering are separate workloads. A faster batch conversion does not increase a game's simulation frame rate, and an upscaler is not run for every displayed frame.

## Local preparation measurements

These are one-off measurements from the development machine, not cross-device guarantees. Neural runs used Real-ESRGAN x4 anime, Vulkan, tile size 128 and the same 512 source images. Actual time varies with drivers, thermal state and other GPU work.

| Configuration | Images | Processing workers | Time |
|---|---:|---:|---:|
| RTX 2050, prior small batches | 256 | 1 | 26.338 s |
| RTX 2050, shared model context | 256 | 1 | 7.639 s |
| RTX 2050, shared model context | 256 | 2 | 5.894 s |
| AMD integrated graphics | 256 | 1 | 17.471 s |
| RTX 2050, shared model context | 512 | 2 | 7.777 s |
| CPU Fast Pixel (Scale2x) | 256 | 1 | 2.351 s |

The RTX 2050 two-worker run peaked at about 1.65 GiB dedicated GPU memory. Four and eight workers exceeded the project's 2 GiB profiling target and were stopped. Larger neural tiles also used substantially more memory. Current limits prioritize predictable memory use over maximizing worker count.

The CPU row uses deterministic Scale2x, not neural inference; it produces a different visual result and is not directly comparable to Real-ESRGAN quality.

## What is included in these timings

The model throughput benchmark measures invocation and image processing. It does not include all archive inspection, persistent cache validation and publishing. A separate isolated service run processed 256 sources in 37.491 seconds end-to-end, including registration, validation, queue/storage work, image writing and ready-index publication.

The player does not wait for every artwork job before starting. Prepared artwork is reused; a missing replacement falls back to the game's normal source/render path. Background work is bounded and yields while the game is active unless current resource and frame measurements permit a small job.

## Reproduce

Use a directory of source PNGs that you are permitted to use. Results are written under the ignored build folder; existing game caches are not overwritten.

~~~powershell
./.venv/Scripts/python.exe tools/profile_enhancement_devices.py <source-png-directory> --count 256 --configs 256:1:128,256:2:128
./.venv/Scripts/python.exe tools/profile_enhancement_devices.py <source-png-directory> --count 512 --device-kinds dedicated --configs 64:1:128,256:1:128,512:1:128,512:2:128
./.venv/Scripts/python.exe tools/check_ai_batch.py <source-png-directory> <profile-results.json>
~~~

The profiling tools use Windows performance counters and GPU-specific telemetry. Reports from one machine should not be treated as target guarantees for other hardware.
