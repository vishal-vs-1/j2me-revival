from pathlib import Path
import subprocess,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from engine import locate_java
classes=ROOT/'build/classes'
subprocess.run([locate_java('javac'),'--release','8','-cp',str(classes),'-d',str(classes),str(ROOT/'tests/LifecycleCheck.java')],check=True)
subprocess.run([locate_java(),'-Djava.awt.headless=true','-cp',str(classes),'LifecycleCheck'],check=True,timeout=10)
