from pathlib import Path
import subprocess
import sys
import zipfile
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from engine import locate_java


def build_demo(classes):
    output = ROOT / 'build/demo'
    output.mkdir(parents=True, exist_ok=True)
    subprocess.run([locate_java('javac'), '--release', '8', '-cp', str(classes), '-d', str(output), str(ROOT/'fixtures/RevivalDemo.java')], check=True)
    car = Image.new('RGBA', (24,40))
    d=ImageDraw.Draw(car)
    d.polygon([(7,0),(16,0),(20,7),(21,33),(17,39),(6,39),(2,33),(3,7)], fill='#e54b56')
    d.rectangle((5,9,18,17), fill='#9ce8ea')
    d.rectangle((6,26,17,31), fill='#3e7084')
    d.rectangle((1,8,3,15), fill='#142033'); d.rectangle((20,8,22,15), fill='#142033')
    d.rectangle((1,27,3,35), fill='#142033'); d.rectangle((20,27,22,35), fill='#142033')
    d.line((8,3,8,7),fill='#fff4ac',width=2); d.line((15,3,15,7),fill='#fff4ac',width=2)
    d.line((6,34,17,34),fill='#ffb778',width=2)
    car.save(output/'car.png')
    tile=Image.new('RGBA',(80,80),'#344355'); d=ImageDraw.Draw(tile)
    for y in range(0,80,8):
        for x in range(0,80,8):
            if (x+y)%24==0: d.rectangle((x,y,x+2,y+2),fill='#3c4d60')
    tile.save(output/'track.png')
    with zipfile.ZipFile(ROOT/'fixtures/RevivalDemo.jar','w',zipfile.ZIP_DEFLATED) as jar:
        manifest=zipfile.ZipInfo('META-INF/MANIFEST.MF',(2026,1,1,0,0,0))
        manifest.compress_type=zipfile.ZIP_DEFLATED
        jar.writestr(manifest,'Manifest-Version: 1.0\nMIDlet-Name: Revival Demo\nMIDlet-Version: 1.0\nMIDlet-Vendor: JAR Revival\nMIDlet-1: Revival Demo,/car.png,RevivalDemo\nMicroEdition-Profile: MIDP-2.0\nMicroEdition-Configuration: CLDC-1.1\n\n')
        for p in sorted(output.iterdir()):
            # Stable archive metadata makes repeated builds import as the same game.
            info=zipfile.ZipInfo(p.name,(2026,1,1,0,0,0))
            info.compress_type=zipfile.ZIP_DEFLATED
            jar.writestr(info,p.read_bytes())


if __name__=='__main__':
    build_demo(ROOT/'build/classes')
