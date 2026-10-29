from pathlib import Path
import subprocess,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from engine import locate_java
classes=ROOT/'build/classes';out=ROOT/'build/paint-check';out.mkdir(exist_ok=True)
subprocess.run([locate_java('javac'),'--release','8','-cp',str(classes),'-d',str(classes),str(ROOT/'tests/PaintWaitCheck.java')],check=True)
subprocess.run([locate_java(),'-Djava.awt.headless=true','-Dfile.encoding=ISO_8859_1','-cp',str(classes),'PaintWaitCheck'],cwd=out,check=True,timeout=15)
