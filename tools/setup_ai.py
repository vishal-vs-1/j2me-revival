"""Download the official free Real-ESRGAN runtime for the current platform into this project."""
from pathlib import Path
import hashlib
import json
import shutil
import sys
import urllib.request
import zipfile

if not getattr(sys, 'frozen', False):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app_paths import DATA_ROOT as ROOT
from platform_support import IS_WINDOWS, IS_LINUX, ncnn_binary_name

# Official upstream binaries from https://github.com/xinntao/Real-ESRGAN/releases/tag/v0.2.5.0
_PLATFORM_URL = {
    'windows': 'https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesrgan-ncnn-vulkan-20220424-windows.zip',
    'linux':   'https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesrgan-ncnn-vulkan-20220424-ubuntu.zip',
}


def _platform_key():
    if IS_WINDOWS:
        return 'windows'
    if IS_LINUX:
        return 'linux'
    raise NotImplementedError(f'AI binary download is not yet supported on {sys.platform}. '
                              'Build Real-ESRGAN NCNN Vulkan from source and place the binary in tools/ai/.')


import tempfile


def install(progress=print):
    target = ROOT / 'tools/ai'
    target.mkdir(parents=True, exist_ok=True)
    binary_name = ncnn_binary_name()
    executable = list(target.rglob(binary_name))
    if executable:
        models = list((executable[0].parent / 'models').glob('*.param'))
        if models:
            progress('Free local AI runtime is already installed.')
            return executable[0]
    platform_key = _platform_key()
    url = _PLATFORM_URL[platform_key]
    progress(f'Downloading the official Real-ESRGAN runtime and models ({platform_key})…')
    request = urllib.request.Request(url, headers={'User-Agent': 'JAR-Revival/0.2'})

    with tempfile.TemporaryDirectory(prefix='realesrgan-setup-') as temp_dir_str:
        temp_dir = Path(temp_dir_str)
        archive = temp_dir / 'runtime.zip'
        with urllib.request.urlopen(request, timeout=120) as response, archive.open('wb') as out:
            shutil.copyfileobj(response, out)
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()

        extracted_dir = temp_dir / 'extracted'
        extracted_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive) as z:
            for info in z.infolist():
                destination = (extracted_dir / info.filename).resolve()
                if not destination.is_relative_to(extracted_dir.resolve()):
                    raise ValueError(f'Unexpected archive path: {info.filename}')
            z.extractall(extracted_dir)

        found_executables = list(extracted_dir.rglob(binary_name))
        if not found_executables:
            raise RuntimeError(f'Downloaded archive has no expected runtime ({binary_name})')
        temp_exe = found_executables[0]

        # Validate models directory and model files
        models_dir = temp_exe.parent / 'models'
        if not models_dir.is_dir() or not list(models_dir.glob('*.param')):
            raise RuntimeError('Downloaded archive is missing required model files (*.param) in models/')

        if not IS_WINDOWS:
            temp_exe.chmod(temp_exe.stat().st_mode | 0o111)

        # Staging validated; copy verified files into target
        for item in extracted_dir.iterdir():
            dest = target / item.name
            if dest.is_dir():
                shutil.rmtree(dest)
            elif dest.is_file():
                dest.unlink()
            if item.is_dir():
                shutil.copytree(item, dest)
            else:
                shutil.copy2(item, dest)

        installed_exes = list(target.rglob(binary_name))
        if not installed_exes:
            raise RuntimeError(f'Installation failed: runtime executable not found in {target}')
        if not IS_WINDOWS:
            for binary in installed_exes:
                binary.chmod(binary.stat().st_mode | 0o111)

        (target / 'download.json').write_text(json.dumps(
            {'platform': platform_key, 'source': url, 'archive_sha256': digest}, indent=2), encoding='utf-8')

    progress('Local AI is installed. Choose AI cartoon in Artwork, then Prepare for an existing game or import a new game.')
    return installed_exes[0]


if __name__ == '__main__':
    install()
