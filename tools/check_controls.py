"""Control contracts independent of GPU drawing, then real LCDUI menu/target checks."""
from pathlib import Path
import os,subprocess,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from engine import locate_java
classes=ROOT/'build/classes';out=ROOT/'build/control-check';out.mkdir(exist_ok=True)
cp=str(classes)+os.pathsep+str(ROOT/'tools/gpu/*')
names=['InputControllerCheck','MenuNavigationCheck','InputTargetCheck','InitialPaintCheck','HeldInputCheck','CanvasStatePolicyCheck','FramePipelineCheck']
subprocess.run([locate_java('javac'),'--release','8','-cp',cp,'-d',str(classes),*[str(ROOT/'tests'/(name+'.java')) for name in names]],check=True)
for name in names:
    result=subprocess.run([locate_java(),'-Djava.awt.headless=true','-Dfile.encoding=ISO_8859_1','-cp',cp,name],cwd=out,capture_output=True,text=True,timeout=15)
    print(result.stdout.strip(),flush=True)
    if result.returncode:print(result.stderr);raise SystemExit(result.returncode)
