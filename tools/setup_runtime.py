"""Create a private Java runtime so GPU preferences never modify every Java application."""
from pathlib import Path
import subprocess,sys,json
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from engine import locate_java

def install():
    target=ROOT/'tools/runtime'
    if (target/'bin/java.exe').exists():return target
    if target.exists():raise RuntimeError('An incomplete runtime exists at tools/runtime. Preserve or rename it before rebuilding.')
    linker=locate_java('jlink')
    print('Creating the private player Java runtime…',flush=True)
    subprocess.run([linker,'--add-modules','java.se,jdk.unsupported','--strip-debug','--no-header-files','--no-man-pages','--output',str(target)],check=True)
    (target/'build-info.json').write_text(json.dumps({'jlink':linker,'modules':['java.se','jdk.unsupported']},indent=2))
    print('Private player runtime ready:',target,flush=True);return target

if __name__=='__main__':install()
