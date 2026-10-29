"""Probe Mr Bean startup with isolated settings and capture both render surfaces."""
from pathlib import Path
import subprocess,argparse
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from engine import Library,locate_java
parser=argparse.ArgumentParser();parser.add_argument('--scale',type=int,default=4);parser.add_argument('--screen',default='240x320');parser.add_argument('keys',nargs='*',type=int)
args=parser.parse_args();width,height=map(int,args.screen.split('x'))
l=Library(); g=next(g for g in l.games() if 'Bean' in g['name'])
folder=l.workspace(g['id']); out=ROOT/f'build/mrbean-check-{args.screen}-{args.scale}'; out.mkdir(parents=True,exist_ok=True)
classes=ROOT/'build/classes'
subprocess.run([locate_java('javac'),'--release','8','-cp',str(classes),'-d',str(classes),str(ROOT/'tests/GameProbe.java')],check=True)
with (out/'probe.log').open('w') as log:
    result=subprocess.run([locate_java(),'-Djava.awt.headless=true','-Dfile.encoding=ISO_8859_1',f'-Djme.scale={args.scale}',f'-Djme.width={width}',f'-Djme.height={height}',
        f'-Djme.pack={folder}',f'-Djme.textures={l.texture_dir(folder,g.get("backend","pixel"))}',
        '-cp',str(classes)+';'+str(ROOT/'vendor/freej2me-plus/resources'),'GameProbe',
        str(l.library/g['id']/'game.jar'),str(out),*[str(k) for k in args.keys]],cwd=out,stdout=log,stderr=subprocess.STDOUT,timeout=45)
print((out/'probe.log').read_text(errors='replace')[-5000:])
raise SystemExit(result.returncode)
