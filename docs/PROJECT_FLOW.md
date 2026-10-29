# Project flow

This document describes the implementation that exists in the repository. It separates import/preparation from playback so that artwork work cannot change game timing or input behavior.

## High-level flow

~~~mermaid
flowchart TD
    A[Start the desktop library] --> B[Select or import a game JAR]
    B --> C[Copy and fingerprint the original JAR]
    C --> D[Inspect archive and discover supported image sources]
    D --> E[Normalize image identity and enhancement recipe]
    E --> F{Prepared result cached?}
    F -- yes --> G[Reuse saved result]
    F -- no --> H[Queue bounded background work]
    H --> I{Selected artwork style}
    I -- Fast Pixel --> J[Scale2x on CPU]
    I -- AI Cartoon --> K[Real-ESRGAN NCNN/Vulkan]
    J --> L[Validate and persist enhanced image]
    K --> L
    G --> M[Launch original game through patched FreeJ2ME-Plus]
    L --> M
    M --> N[GPU compositor presents cached art]
    M --> O[Observe eligible decoded/offscreen sources]
    O --> P[Persist stable runtime source candidates]
    P --> E
~~~

## Step-by-step: import and prepare

| Step | Components | What happens |
|---|---|---|
| 1. UI request | **app.py**, **ui_widgets.py** | The user chooses a JAR and an artwork style. UI callbacks submit work and display status. |
| 2. Copy and identify | **engine.py**, **game_storage.py** | The original JAR is copied into the local library and identified by content hash. Output paths are constrained to the application's data roots. |
| 3. Inspect and discover | **game_inspection.py**, **asset_decoding.py**, **gameloft_resources.py** | Archive metadata, ordinary images, validated embedded PNGs, and recognized bounded containers are inspected. Unknown/private data stays opaque. No game code runs during this scan. |
| 4. Normalize and schedule | **runtime_assets/contracts.py**, **runtime_assets/service.py**, **runtime_assets/store.py**, **runtime_assets/resources.py** | Sources receive stable pixel identities and recipe identities. Duplicate work is reused; memory-aware limits bound queued/in-flight jobs. |
| 5. Enhance | **runtime_assets/backends.py**, **ai_backend.py**, **engine.py**, **atlas_enhancement.py** | The selected backend prepares an image outside the game/render thread. AI Cartoon invokes the local NCNN/Vulkan model; Fast Pixel uses deterministic Scale2x. |
| 6. Validate and publish | **runtime_assets/store.py**, **runtime_assets/service.py** | The generated output is validated and stored with its source/recipe identity. Failed work remains retryable; a partial result is not marked ready. |

Repeated preparation reuses results whose source and recipe still match. Changing enhancement style creates or selects a separate recipe result instead of overwriting the original source.

## Step-by-step: play and runtime discovery

| Step | Components | What happens |
|---|---|---|
| 1. Resolve launch policy | **engine.py**, **execution_policy.py**, **gpu_policy.py**, **startup_cleaner.py** | The launcher resolves saved screen/render settings and execution preferences. An optional startup repair applies only to its reviewed exact JAR fingerprint; it is off by default and leaves the imported original untouched. |
| 2. Start the emulator | **tools/build.py**, **tools/patch_emulator.py**, **emulator-src/** | The build fetches a pinned FreeJ2ME-Plus revision, applies the integration patch, and builds the player. The running game remains the original Java ME program. |
| 3. Deliver controls | **GpuPlayer**, **DesktopKeyMap**, **KeyInputController**, **MobileInputSink** | Desktop keyboard events are translated to Java ME key events. The mapping, held-key policy, and emulator delivery are separate components. |
| 4. Compose frames | **GpuRenderer**, **Enhancement**, **TextureRepository**, **TexturePool**, **TextureUpdateQueue** | OpenGL presents the game at desktop height while preserving the logical aspect ratio. Matching prepared artwork is used where supported; original game pixels remain the source of truth for game logic and readback. |
| 5. Observe new assets | **ObservationRegistry**, **ImageObservation**, **CaptureAdmission**, **CaptureWriter**, **RuntimeAssets** | Shared emulator hooks can record eligible immutable images, stable offscreen images, derived images, and sampled RGB blocks. Dynamic screen buffers are excluded. |
| 6. Prepare for future launches | **runtime_assets/** | Stable discovered sources join the same generic identity/cache pipeline. They can be prepared after the player closes and reused later. |

## Build tools and libraries

| Tool or library | Role in the flow |
|---|---|
| Python and Tkinter | Desktop library, import orchestration, filesystem/cache work and background preparation. |
| Pillow and NumPy | Image decoding, pixel normalization, alpha handling, resizing and deterministic filters. |
| Real-ESRGAN NCNN/Vulkan | Optional local 4× AI Cartoon preparation. Installed by **tools/setup_ai.py**; inference does not call a hosted API. |
| FreeJ2ME-Plus | Java ME runtime/emulator base, fetched at a pinned upstream revision by **tools/build.py**. |
| LWJGL and GLFW | Native window, keyboard events and OpenGL access for GPU presentation. Downloaded by **tools/setup_gpu.py**. |
| JDK tools | Compile the patched emulator and create the private player runtime with **javac** and **jlink**. |

## Boundaries and data guarantees

- **Original JAR:** retained as imported. The player does not replace source assets inside it.
- **Logical game surface:** dimensions and coordinates used by game code remain independent from the desktop presentation size.
- **Enhancement:** a prepared image is a display replacement keyed to its source and recipe; it does not change physics, frame timing, collision or animation logic.
- **Cache:** generated assets and game saves are stored under local per-game data. Reopening the tool does not rerun completed conversions.
- **Unknown formats:** unsupported packed images remain unverified and use the game's normal decode/render path.
- **Compatibility exceptions:** new policies should be opt-in, data-driven and narrowly matched to evidence. They should not alter renderer or input defaults for unrelated JARs.

## Source organization

- Root Python modules handle the desktop app, library state, import, policies and image backends.
- **runtime_assets/** groups the shared source contracts, persistence, scheduling and enhancement backends.
- **emulator-src/** contains the Java integration classes in the shared **org.recompile.mobile** package. The patcher and focused checks currently expect this source layout, so files have not been moved or renamed in this cleanup.
- **tools/** contains reproducible build/setup scripts and independent diagnostics.
- **tests/** contains Python contract tests and Java integration checks.

The module and class names reflect these roles. This repository-preparation change keeps runtime source paths stable instead of performing a broad package refactor that could break the patcher or test harness.
