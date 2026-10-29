from pathlib import Path
import os,subprocess,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from engine import locate_java
classes=ROOT/'build/classes';out=ROOT/'build/input-check';out.mkdir(exist_ok=True)
classpath=str(classes)+os.pathsep+str(ROOT/'tools/gpu/*')
subprocess.run([locate_java('javac'),'--release','8','-cp',classpath,'-d',str(classes),str(ROOT/'tests/HeldInputCheck.java')],check=True)
subprocess.run([locate_java(),'-Djava.awt.headless=true','-Dfile.encoding=ISO_8859_1','-cp',classpath,'HeldInputCheck'],cwd=out,check=True,timeout=15)
