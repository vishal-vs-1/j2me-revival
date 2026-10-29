# JAR Revival

JAR Revival is a Windows desktop library for running Java ME (J2ME) games with locally prepared higher-resolution artwork. It keeps the original game JAR and game logic, and uses FreeJ2ME-Plus as its emulator base.

> **Project status:** experimental. The app and rendering pipeline work, but compatibility and artwork coverage vary by game. It is not a JAR-to-Windows-game converter.

## Features

- Import and organize J2ME game JARs in a local library.
- Prepare 2D images once with **Fast Pixel** (Scale2x) or optional local **AI Cartoon** (Real-ESRGAN NCNN/Vulkan).
- Cache prepared assets for later launches.
- Play through a desktop GPU compositor with keyboard controls, aspect-preserving scaling and a CPU compatibility option.
- Keep game logic and original logical pixels intact while presenting cached artwork at higher detail.
- Optionally observe eligible images discovered by the emulator at runtime and prepare them for later use.

Image enhancement is local. There is no paid inference API. The optional model installer downloads its runtime and weights from their upstream source. User-imported games are not included in this repository.

## Build and run

Development has been exercised on Windows with Python 3.14 and a JDK. You need:

- Windows 10 or 11
- Python 3.10+ with Tkinter
- JDK 17+ providing javac and jlink
- Git
- Internet access for the initial emulator/dependency build and optional AI setup

From the project folder, run:

~~~powershell
py -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements.txt
./.venv/Scripts/python.exe tools/build.py
~~~

The build fetches the pinned FreeJ2ME-Plus source, applies this project's emulator integration, compiles the player, prepares a private Java runtime, installs the GPU bindings, and builds the synthetic Revival Demo fixture.

To use AI Cartoon, install the optional local enhancement runtime:

~~~powershell
./.venv/Scripts/python.exe tools/setup_ai.py
~~~

Then start the library:

~~~powershell
./.venv/Scripts/python.exe app.py
~~~

After the first build, Start.cmd can also launch the app. It prefers the project virtual environment when present. Fast Pixel works without the AI runtime.

## First game

1. Choose an artwork style.
2. Select **Add game** and choose a JAR you are allowed to use.
3. Wait for the game to be inspected and its initial artwork to be prepared.
4. Select it and choose **Play**. Use the keyboard controls shown in the player title bar.

Only import games you have the right to use. A game JAR contains executable Java code; this project runs it inside the emulator and is **not a security sandbox**.

## Data and limitations

- The imported JAR is copied into the local library and is not rewritten. Saves and generated artwork stay on the computer.
- Ordinary images and a few validated container layouts can be extracted before play. Some games create sprites from private packed bytes; those formats cannot all be decoded generically.
- Runtime observation can discover some stable decoded artwork, but does not guarantee complete coverage. A game must be played to expose dynamic assets.
- Neural upscaling can smooth or invent details and can damage small text, faces and logos. Scale2x is deterministic and conservative, but does not create new artwork detail.
- Animation timing and game logic remain original. This tool does not interpolate animation frames or remaster 3D models.
- A successful import means the JAR can be launched; it does not certify every screen, level, control or rendering path.

## Project flow and developer notes

- [Project flow and component responsibilities](docs/PROJECT_FLOW.md)
- [Asset decoding and runtime discovery](docs/ASSET_DECODING.md)
- [Development and verification](docs/DEVELOPMENT.md)
- [Performance measurements and limits](docs/PERFORMANCE.md)

## License

This project is licensed under GPL-3.0-or-later. The included license file retains the upstream FreeJ2ME and ASM notices. FreeJ2ME-Plus and downloaded libraries/models have their own notices and terms; see the build scripts and their upstream projects before redistributing a packaged build. The app does not bundle user game JARs.
