from pathlib import Path
import os,subprocess,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from engine import locate_java
classes=ROOT/'build/classes';out=ROOT/'build/gpu-check';out.mkdir(exist_ok=True)
classpath=str(classes)+os.pathsep+str(ROOT/'tools/gpu/*')
subprocess.run([locate_java('javac'),'--release','8','-cp',classpath,'-d',str(classes),str(ROOT/'tests/GpuCheck.java'),str(ROOT/'tests/FastScalerCheck.java'),str(ROOT/'tests/RawRgbGpuCheck.java'),str(ROOT/'tests/M3gGpuCheck.java')],check=True)
subprocess.run([locate_java(),'-Djme.gpu=true','-Djme.scale=4','-cp',classpath,'GpuCheck',str(out/'proof.png')],cwd=out,check=True,timeout=45)
subprocess.run([locate_java(),'-Djme.gpu=true','-Djme.scale=2','-cp',classpath,'FastScalerCheck'],cwd=out,check=True,timeout=45)
subprocess.run([locate_java(),'-Djme.gpu=true','-Djme.scale=4','-cp',classpath,'FastScalerCheck'],cwd=out,check=True,timeout=45)
for scale in (2,4):
    subprocess.run([locate_java(),'-Djme.gpu=true',f'-Djme.scale={scale}','-cp',classpath,
                    'org.recompile.mobile.M3gGpuCheck',str(out/f'm3g-after-{scale}')],cwd=out,check=True,timeout=45)
    subprocess.run([locate_java(),'-Djme.gpu=true',f'-Djme.scale={scale}','-cp',classpath,
                    'org.recompile.mobile.RawRgbGpuCheck',str(out)],cwd=out,check=True,timeout=45)
