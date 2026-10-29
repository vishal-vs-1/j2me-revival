# JAR Revival

[![Checks](https://github.com/vishal-vs-1/j2me-revival/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/vishal-vs-1/j2me-revival/actions/workflows/ci.yml)
[![License: GPL-3.0-or-later](https://img.shields.io/badge/License-GPL--3.0--or--later-blue.svg)](LICENSE)

**Play classic Java ME phone games on Windows, with locally enhanced artwork and a desktop-sized view.**

JAR Revival imports your own J2ME games into a persistent library. It runs them with [FreeJ2ME-Plus](https://github.com/TASEmulators/freej2me-plus), prepares supported images with a local pixel scaler or optional Real-ESRGAN AI, and presents the game at desktop height while keeping its original proportions and logic.

<p align="center">
  <img src="docs/images/revival-demo-gameplay.png" alt="Gameplay from the included synthetic Revival Demo" width="360">
  <br><em>Included synthetic demo; no game JAR is bundled.</em>
</p>

## Real-game artwork: Mr Bean Racer 2

This is the same 176 × 220 title image from a local MrBeanRacer2 import, shown at 4× (704 × 880). The original uses nearest-neighbor enlargement; the other panels are the saved Fast Pixel and Real-ESRGAN AI Cartoon outputs from this project. This is extracted title artwork, not a gameplay frame.

<table>
  <thead>
    <tr>
      <th>Original · nearest-neighbor 4×</th>
      <th>Fast Pixel · 4×</th>
      <th>AI Cartoon · 4×</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><img src="docs/images/mrbean-racer-2-original-nearest-4x.png" alt="Mr Bean Racer 2 title image enlarged 4× with nearest-neighbor sampling" width="220"></td>
      <td><img src="docs/images/mrbean-racer-2-fast-pixel-4x.png" alt="Same Mr Bean Racer 2 image enlarged 4× with Fast Pixel" width="220"></td>
      <td><img src="docs/images/mrbean-racer-2-ai-cartoon-4x.png" alt="Same Mr Bean Racer 2 image enlarged 4× with Real-ESRGAN AI Cartoon" width="220"></td>
    </tr>
  </tbody>
</table>

<p><em>The MrBeanRacer2 JAR is not bundled; this comparison includes its title artwork. AI redraws the face and lettering, so the larger image is not a fully faithful restoration.</em></p>

## Bounce Tales artwork

This is the same 168 × 121 logo image from a local Bounce Tales import, shown at 4× (672 × 484). The first panel enlarges the original with nearest-neighbor sampling; the others show Fast Pixel and the locally generated Real-ESRGAN AI Cartoon output.

<table>
  <thead>
    <tr>
      <th>Original · nearest-neighbor 4×</th>
      <th>Fast Pixel · 4×</th>
      <th>AI Cartoon · 4×</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><img src="docs/images/bounce-tales-original-nearest-4x.png" alt="Bounce Tales logo enlarged 4× with nearest-neighbor sampling" width="220"></td>
      <td><img src="docs/images/bounce-tales-fast-pixel-4x.png" alt="Bounce Tales logo enlarged 4× with Fast Pixel" width="220"></td>
      <td><img src="docs/images/bounce-tales-ai-cartoon-4x.png" alt="Bounce Tales logo enlarged 4× with Real-ESRGAN AI Cartoon" width="220"></td>
    </tr>
  </tbody>
</table>

<p><em>The Bounce Tales JAR is not bundled; the images show one extracted logo resource, not gameplay. AI visibly redraws the ball and lettering, so inspect details before choosing this style for a game.</em></p>

## What you can do

- Import JARs and keep a searchable local library with saved artwork and game data.
- Prepare supported 2D artwork with **Fast Pixel** or optional local **AI Cartoon**. Results are cached and reused.
- Play in a desktop-sized, aspect-preserving window with keyboard controls and a CPU compatibility option.
- Compare enhanced presentation with the original and keep the source JAR unchanged.
- Run enhancement locally; game files and artwork are not uploaded.

## Try it on Windows

You need Windows 10 or 11, Python 3.10+ with Tkinter, a JDK 17+ with `javac` and `jlink`, and Git. The first build downloads the pinned emulator source and graphics libraries.

~~~powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe tools/build.py
.\.venv\Scripts\python.exe app.py
~~~

After launching, click **Import demo** in the sidebar to try the included synthetic game. It exercises the player without bundling a commercial title and is not evidence of broad compatibility. To use your own game, click **Add game** and choose a JAR you have the right to use. For AI artwork, run `tools/setup_ai.py` once; **Fast Pixel** works without the model.

1. Choose an artwork style and select the game in your library.
2. Wait for its import to finish, then choose **Play enhanced**. Controls appear in the player window.

## What to expect

This is an experimental project. Standard images and some recognized containers can be prepared before play. Some games store graphics in private formats, so only part of their artwork may be enhanced. Runtime discovery can find some additional stable images, but it does not promise full-game coverage.

AI enhancement can change small details, text, faces, or logos. Animation timing and game logic remain original; this project does not interpolate frames or remaster 3D models. A successful import means a game can launch, not that every level, control, or drawing path has been verified.

Only import games you are allowed to use. A JAR contains executable Java code; the emulator is not a security sandbox.

## For contributors

- [Project flow and component responsibilities](docs/PROJECT_FLOW.md)
- [Asset decoding and runtime discovery](docs/ASSET_DECODING.md)
- [Development setup and verification](docs/DEVELOPMENT.md)
- [Performance measurements and limits](docs/PERFORMANCE.md)

The Python contract suite runs on Windows for pushes and pull requests. Focused emulator and graphics checks are described in the development guide; some require a built player, a graphics driver, or a user-provided game.

## License

JAR Revival is GPL-3.0-or-later. FreeJ2ME-Plus, downloaded libraries, the optional model, and the Java runtime have their own notices and terms. Review upstream terms before redistributing a packaged build. User-imported game JARs are not included.
