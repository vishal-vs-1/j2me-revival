from pathlib import Path
import json,subprocess,sys,os
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from engine import locate_java
classes=ROOT/'build/classes'; out=ROOT/'build/render-benchmark';out.mkdir(exist_ok=True)
classpath=str(classes)+os.pathsep+str(ROOT/'tools/gpu/*')
subprocess.run([locate_java('javac'),'--release','8','-cp',classpath,'-d',str(classes),str(ROOT/'tests/RenderBenchmark.java')],check=True)
results=[]
for scale in [1,2,4]:
    text=subprocess.check_output([locate_java(),'-Djava.awt.headless=true',f'-Djme.scale={scale}','-cp',classpath,'RenderBenchmark'],cwd=out,text=True,timeout=60)
    result=json.loads(text.strip().splitlines()[-1]);results.append(result);print(result,flush=True)
name=sys.argv[1] if len(sys.argv)>1 else 'latest'
(out/(name+'.json')).write_text(json.dumps(results,indent=2))
