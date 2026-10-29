JAR Revival - Windows x64 preview

START HERE
1. Extract the entire ZIP to a folder you can write to.
2. Open JAR Revival.exe. Keep the app and data folders beside it.
   Python, Java, and Git do not need to be installed separately.
3. Click Import demo at the bottom of the left sidebar, or use Add game
   to import your own J2ME game JAR. The demo is not added automatically.
4. Select the game in your library, wait for its import to finish, then
   open the Play tab and click Play enhanced.

The included Revival Demo is synthetic. No commercial game JAR is included.
Fast pixel is ready immediately and works offline.

OPTIONAL AI CARTOON
The AI runtime and model are not included in this ZIP.
1. Connect to the internet and open the Artwork tab.
2. Click AI setup. Wait for the status at the bottom of the window to say
   Local AI is installed. This downloads the official free Real-ESRGAN
   runtime and models once into data\tools\ai in this folder.
3. Choose AI cartoon in the Artwork style selector.
4. For a game already in your library, select it and click Prepare.
   For a new game, choose AI cartoon before Add game or Import demo.
5. Open the Play tab and click Play enhanced.

AI requires a working Vulkan-capable graphics driver. After setup, AI runs
locally and works offline. Your games and artwork are not uploaded.
If the download fails, check the connection and click AI setup again.

YOUR FILES
app contains the bundled runtimes and support files. Keep it with the EXE.
data contains your library, saves, settings, artwork cache, and downloaded AI.
Keep data when upgrading. The app creates its contents as you use it.

UPGRADING FROM THE EARLIER PREVIEW
Close the old app. Copy its library and rendered-games folders into this
version's data folder. If AI was already installed, copy the old tools\ai
folder into data\tools\ai. Keep the old copy until your games and saves
are visible in this version.

NOTICES
Project license: app\LICENSE
Python, NumPy, Pillow notices: app\THIRD-PARTY-LICENSES
Java notices: app\tools\runtime\legal
Graphics notices: app\tools\gpu
FreeJ2ME notice: inside app\build\jme-player.jar

This is an experimental preview. Compatibility and artwork coverage vary
by game. Import only game JARs you are allowed to use.
