# Development

## Setup

Use the build steps in the root [README](../README.md). **tools/build.py** fetches the pinned emulator source and prepares the native and Java components. The optional AI runtime is installed separately by **tools/setup_ai.py**.

Install **requirements-dev.txt** instead of **requirements.txt** when running the Python tests; it includes the runtime dependencies plus pytest.

The build creates generated files under **build/**, **tools/gpu/**, **tools/runtime/**, and **vendor/**. These are excluded from Git. Do not copy downloaded runtime/model binaries or user game assets into the source tree for a commit.

## Verify changes

Run the Python contract suite:

~~~powershell
./.venv/Scripts/python.exe -m pytest tests -q
~~~

The emulator integration has focused checks. Most Java checks build or use the player first; GPU checks require a working OpenGL/Vulkan driver, and real-game checks require the corresponding user-provided JAR.

~~~powershell
./.venv/Scripts/python.exe tools/check_renderer.py
./.venv/Scripts/python.exe tools/check_gpu.py
./.venv/Scripts/python.exe tools/check_input.py
./.venv/Scripts/python.exe tools/check_controls.py
./.venv/Scripts/python.exe tools/check_menu_player.py
./.venv/Scripts/python.exe tools/check_menu_presentation.py
./.venv/Scripts/python.exe tools/check_lifecycle.py
~~~

Not every game or state is covered by the synthetic tests. A successful test run is evidence for the tested contracts, not proof of universal JAR compatibility.

## Change boundaries

- Keep key mapping, input state, rendering, game execution policy and asset preparation in their existing modules.
- Add a game-format adapter only when a resource structure is verified; never infer support from a filename or game title alone.
- Keep source identity and enhancement recipe versioned so cached images cannot be mistaken for outputs of a different pipeline.
- Do not run model inference on the game/render thread.
- Preserve original game coordinates and source pixels for readback.
- Add a regression check for the old failure and a focused check for the affected adjacent behavior before broad changes.

The Java integration helpers intentionally remain together in **org.recompile.mobile**. **tools/patch_emulator.py** and existing checks resolve their current source paths. A future package-layout refactor should update the patcher and checks in one isolated change.
