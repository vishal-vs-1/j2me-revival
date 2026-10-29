from pathlib import Path
import json,subprocess,sys,os
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from engine import locate_java
classes=ROOT/'build/classes';out=ROOT/'build/gpu-check';out.mkdir(exist_ok=True)
classpath=str(classes)+os.pathsep+str(ROOT/'tools/gpu/*')
subprocess.run([locate_java('javac'),'--release','8','-cp',classpath,'-d',str(classes),str(ROOT/'tests/RenderBenchmark.java'),str(ROOT/'tests/GpuBenchmark.java')],check=True)
text=subprocess.check_output([locate_java(),'-Djme.gpu=true','-Djme.scale=4','-cp',classpath,'GpuBenchmark'],cwd=out,text=True,timeout=60)
print(text);(out/'benchmark.json').write_text(text)
