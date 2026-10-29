"""Build the portable ZIP after tools/build.py has built the player and demo.

Build dependencies: python -m pip install -r requirements.txt pyinstaller==6.22.3
Run on Windows: python tools/package_windows.py
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import sysconfig
import zipfile


ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / '.runtime' / 'windows-package'
DIST = WORK / 'dist'
APP = DIST / 'JAR Revival'
CONTENTS = APP / 'app'
OUTPUT = ROOT / 'build' / 'windows-release'
ARCHIVE_NAME = 'JAR-Revival-Windows-x64-preview.zip'


def require(path):
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f'Required release input is missing: {path}')
    return path


def copy(source, destination):
    source = require(source)
    if source.is_dir():
        shutil.copytree(source, destination, dirs_exist_ok=True)
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def make_runtime():
    if sys.platform != 'win32':
        raise RuntimeError('Build the Windows package on Windows.')
    # Only this dedicated, regenerable working directory may be removed.
    work = WORK.resolve()
    if work != ROOT / '.runtime' / 'windows-package' or WORK.is_symlink():
        raise RuntimeError('Unexpected packaging work directory.')
    if WORK.exists():
        shutil.rmtree(WORK)
    WORK.mkdir(parents=True)
    hook = WORK / 'portable_runtime_hook.py'
    hook.write_text(
        "import os, sys, traceback\n"
        "from pathlib import Path\n"
        "_resources = Path(sys._MEIPASS)\n"
        "_data = Path(sys.executable).resolve().parent / 'data'\n"
        "os.environ.setdefault('JME_JAVA_HOME', str(_resources / 'tools/runtime'))\n"
        "def _log_uncaught(kind, value, tb):\n"
        "    _data.mkdir(parents=True, exist_ok=True)\n"
        "    with (_data / 'launch-error.log').open('a', encoding='utf-8') as log:\n"
        "        traceback.print_exception(kind, value, tb, file=log)\n"
        "sys.excepthook = _log_uncaught\n",
        encoding='utf-8',
    )
    env = os.environ.copy()
    temporary = WORK / 'temp'
    temporary.mkdir()
    env['TEMP'] = env['TMP'] = str(temporary)
    local_tools = ROOT / '.runtime' / 'package-tools'
    if local_tools.is_dir():
        env['PYTHONPATH'] = str(local_tools) + os.pathsep + env.get('PYTHONPATH', '')
    command = [
        sys.executable, '-m', 'PyInstaller', '--noconfirm', '--onedir',
        '--windowed', '--contents-directory', 'app', '--name', 'JAR Revival',
        '--distpath', str(DIST), '--workpath', str(WORK / 'work'),
        '--specpath', str(WORK), '--runtime-hook', str(hook),
        '--hidden-import', 'tools.setup_ai', str(ROOT / 'app.py'),
    ]
    subprocess.run(command, cwd=ROOT, env=env, check=True)


def add_assets():
    copy(ROOT / 'build/jme-player.jar', CONTENTS / 'build/jme-player.jar')
    copy(ROOT / 'tools/runtime', CONTENTS / 'tools/runtime')
    copy(ROOT / 'tools/gpu', CONTENTS / 'tools/gpu')
    copy(ROOT / 'fixtures/RevivalDemo.jar', CONTENTS / 'fixtures/RevivalDemo.jar')
    copy(ROOT / 'compatibility-src', CONTENTS / 'compatibility-src')
    copy(ROOT / 'LICENSE', CONTENTS / 'LICENSE')
    copy(ROOT / 'docs/README-Windows.txt', APP / 'README.txt')
    (APP / 'data').mkdir(exist_ok=True)
    licenses = CONTENTS / 'THIRD-PARTY-LICENSES'
    copy(Path(sys.prefix) / 'LICENSE.txt', licenses / 'Python-LICENSE.txt')
    site = Path(sysconfig.get_paths()['purelib'])
    for pattern, label in [('numpy-*.dist-info', 'NumPy'), ('pillow-*.dist-info', 'Pillow')]:
        matches = list(site.glob(pattern))
        if len(matches) != 1:
            raise RuntimeError(f'Expected one {label} license metadata directory.')
        metadata = matches[0]
        found = []
        for candidate in metadata.rglob('*'):
            if candidate.is_file() and any(word in candidate.name.lower() for word in ('license', 'copying')):
                copy(candidate, licenses / label / candidate.relative_to(metadata))
                found.append(candidate)
        if not found:
            raise RuntimeError(f'No {label} license files were found.')


def verify_archive(archive):
    with zipfile.ZipFile(archive) as zf:
        if zf.testzip():
            raise RuntimeError('ZIP integrity check failed.')
        names = set(zf.namelist())
        required = {
            'JAR Revival/JAR Revival.exe', 'JAR Revival/README.txt',
            f'JAR Revival/app/python{sys.version_info.major}{sys.version_info.minor}.dll',
            'JAR Revival/app/build/jme-player.jar',
            'JAR Revival/app/fixtures/RevivalDemo.jar',
            'JAR Revival/app/tools/runtime/bin/java.exe',
            'JAR Revival/app/tools/gpu/lwjgl-3.3.6.jar',
            'JAR Revival/app/LICENSE',
            'JAR Revival/app/THIRD-PARTY-LICENSES/Python-LICENSE.txt',
        }
        missing = required - names
        if missing:
            raise RuntimeError('Missing package files: ' + ', '.join(sorted(missing)))
        top = {name.split('/')[1] for name in names if len(name.split('/')) > 1}
        if top != {'JAR Revival.exe', 'README.txt', 'app', 'data'}:
            raise RuntimeError(f'Unexpected top-level package files: {top}')
        for name in names:
            if name.startswith('JAR Revival/data/') and not name.endswith('/'):
                raise RuntimeError('A release must not contain user data.')
            if name.endswith(('.jar', '.jad')) and not (
                name == 'JAR Revival/app/build/jme-player.jar'
                or name == 'JAR Revival/app/fixtures/RevivalDemo.jar'
                or name.startswith('JAR Revival/app/tools/')
            ):
                raise RuntimeError(f'Unexpected game archive: {name}')
        readme = zf.read('JAR Revival/README.txt').decode('utf-8')
        for instruction in ['JAR Revival.exe', 'Import demo', 'Artwork tab', 'AI setup', 'Prepare', 'data\\tools\\ai']:
            if instruction not in readme:
                raise RuntimeError(f'Missing user instruction: {instruction}')


def make_archive():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    archive = OUTPUT / ARCHIVE_NAME
    pending = WORK / ARCHIVE_NAME
    with zipfile.ZipFile(pending, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        zf.writestr('JAR Revival/data/', '')
        for path in sorted(APP.rglob('*')):
            if path.is_file():
                zf.write(path, path.relative_to(DIST).as_posix())
    verify_archive(pending)
    shutil.copy2(pending, archive)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_name(archive.name + '.sha256').write_text(f'{digest}  {archive.name}\n', encoding='ascii')
    return archive, digest


if __name__ == '__main__':
    make_runtime()
    add_assets()
    archive, digest = make_archive()
    print(f'Created {archive} ({archive.stat().st_size:,} bytes)', flush=True)
    print(f'SHA-256: {digest}', flush=True)
