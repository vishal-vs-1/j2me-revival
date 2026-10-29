"""Download the official free Real-ESRGAN Windows runtime into this project."""
from pathlib import Path
import hashlib
import json
import shutil
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
URL = 'https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesrgan-ncnn-vulkan-20220424-windows.zip'


def install(progress=print):
    target=ROOT/'tools/ai'
    target.mkdir(parents=True,exist_ok=True)
    executable=list(target.rglob('realesrgan-ncnn-vulkan.exe'))
    if executable:
        progress('Free local AI runtime is already installed.')
        return executable[0]
    archive=target/'runtime.zip'
    progress('Downloading the official Real-ESRGAN runtime and models…')
    request=urllib.request.Request(URL,headers={'User-Agent':'JAR-Revival/0.1'})
    with urllib.request.urlopen(request,timeout=60) as response, archive.open('wb') as out:
        shutil.copyfileobj(response,out)
    digest=hashlib.sha256(archive.read_bytes()).hexdigest()
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            destination=(target/info.filename).resolve()
            if not destination.is_relative_to(target.resolve()):
                raise ValueError('Unexpected archive path')
        z.extractall(target)
    executable=list(target.rglob('realesrgan-ncnn-vulkan.exe'))
    if not executable: raise RuntimeError('Downloaded archive has no expected runtime')
    (target/'download.json').write_text(json.dumps({'source':URL,'archive_sha256':digest},indent=2))
    progress('Local AI is installed. Select AI cartoon when importing a new game.')
    return executable[0]


if __name__=='__main__': install()
