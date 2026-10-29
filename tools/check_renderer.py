from pathlib import Path
import hashlib
import subprocess
import sys
import numpy as np
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from engine import locate_java, image_id

classes=ROOT/'build/classes'
subprocess.run([locate_java('javac'),'--release','8','-cp',str(classes),'-d',str(classes),str(ROOT/'tests/RendererCheck.java')],check=True)
result=subprocess.run([locate_java(),'-Djava.awt.headless=true','-Djme.scale=4','-cp',str(classes),'RendererCheck',str(ROOT/'build/renderer-check.png')],capture_output=True,text=True,timeout=30)
print(result.stdout)
print(result.stderr)
if result.returncode: raise SystemExit(result.returncode)
colours=[0xff112233,0xffee4455,0xff55ee44,0xff3344cc,0xffcc8844,0xff777777]
a=np.array([[(p>>16)&255,(p>>8)&255,p&255,p>>24] for p in colours],np.uint8).reshape(3,2,4)
expected=image_id(Image.fromarray(a))
assert 'HASH='+expected in result.stdout,'Java/Python canonical hash mismatch'
print('PASS: Java/Python asset identities agree')
