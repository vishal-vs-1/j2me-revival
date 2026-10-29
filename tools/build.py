"""Build the locally modified emulator and synthetic demo without requiring Ant."""
from pathlib import Path
import json
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = '3933e75ef927a95eab9f5e065f0b76dabf336069'
sys.path.insert(0, str(ROOT))
from engine import locate_java
from patch_emulator import patch


def main():
    vendor = ROOT / 'vendor/freej2me-plus'
    if not vendor.exists():
        subprocess.run(['git', 'clone', '--depth', '1', 'https://github.com/TASEmulators/freej2me-plus.git', str(vendor)], check=True)
        subprocess.run(['git','-C',str(vendor),'fetch','--depth','1','origin',UPSTREAM],check=True)
        subprocess.run(['git','-C',str(vendor),'checkout','--detach',UPSTREAM],check=True)
    actual=subprocess.check_output(['git','-C',str(vendor),'rev-parse','HEAD'],text=True).strip()
    if actual != UPSTREAM:
        raise RuntimeError('Emulator checkout differs from the supported pinned revision. Preserve local changes before switching it.')
    patch()
    build_root = (ROOT / 'build').resolve()
    classes = (build_root / 'classes').resolve()
    if classes.parent != build_root or classes.name != 'classes':
        raise RuntimeError('Refusing to clean an unexpected compiler output path.')
    if classes.exists():
        shutil.rmtree(classes)
    classes.mkdir(parents=True, exist_ok=True)
    sources = [p for p in (vendor / 'src').rglob('*.java') if not {'libretro', 'win32pad'}.intersection(p.relative_to(vendor / 'src').parts)]
    argfile = ROOT / 'build/sources.txt'
    argfile.write_text('\n'.join('"'+p.as_posix()+'"' for p in sources), encoding='utf-8')
    gpu=ROOT/'tools/gpu'
    if not list(gpu.glob('lwjgl-*.jar')):
        from setup_gpu import install
        install()
    subprocess.run([locate_java('javac'), '--release', '8', '-encoding', 'UTF-8', '-cp',str(gpu/'*'), '-d', str(classes), '@'+str(argfile)], check=True)
    jar = ROOT / 'build/jme-player.jar'
    with zipfile.ZipFile(jar, 'w', zipfile.ZIP_DEFLATED) as out:
        out.writestr('META-INF/MANIFEST.MF', 'Manifest-Version: 1.0\nMain-Class: org.recompile.freej2me.FreeJ2ME\n\n')
        for base in [classes, vendor / 'resources']:
            for path in base.rglob('*'):
                if path.is_file():
                    out.write(path, path.relative_to(base).as_posix())
        out.write(vendor / 'LICENSE', 'META-INF/FREEJ2ME-LICENSE.txt')
    commit = subprocess.check_output(['git', '-C', str(vendor), 'rev-parse', 'HEAD'], text=True).strip()
    (ROOT / 'build/build-info.json').write_text(json.dumps({'upstream_commit': commit, 'java': locate_java(), 'source': 'FreeJ2ME-Plus + JAR Revival'}, indent=2))
    from make_demo import build_demo
    build_demo(classes)
    from setup_runtime import install
    install()
    print('Built player and demo:', jar)


if __name__ == '__main__':
    main()
