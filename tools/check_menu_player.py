"""Real Mr Bean menu image changes using the same exact-JAR runtime profile as Play."""
from pathlib import Path
import os,shutil,subprocess,sys,time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from engine import Library,locate_java,runtime_arguments
from platform_support import java_binary_name
library=Library();game=next(g for g in library.games() if 'Bean' in g['name']);pack=library.workspace(game['id'])
out=ROOT/'build'/('menu-player-check-'+str(time.time_ns()));shutil.copytree(pack/'saves',out)
cp=str(ROOT/'build/classes')+os.pathsep+str(ROOT/'tools/gpu/*')
subprocess.run([locate_java('javac'),'--release','8','-cp',cp,'-d',str(ROOT/'build/classes'),str(ROOT/'tests/MenuControlProbe.java')],check=True)
with (out/'check.log').open('w') as log:
    process=subprocess.run([str(ROOT/'tools/runtime/bin'/java_binary_name()),'--enable-native-access=ALL-UNNAMED','-Dfile.encoding=ISO_8859_1',
        '-Djme.gpu=true','-Djme.hidden=true','-Djme.stopSeconds=7','-Djme.scale=4','-Dprobe.assertInitialPaint=true',
        *runtime_arguments(game['id']),f'-Djme.pack={pack}',f'-Djme.textures={library.texture_dir(pack,game["backend"])}',
        '-cp',cp,'MenuControlProbe',str(library.library/game['id']/'game.jar'),'176','220','Mr Bean menu check'],
        cwd=out,stdout=log,stderr=subprocess.STDOUT,timeout=18)
text=(out/'check.log').read_text(errors='replace');print(text[-2100:])
assert process.returncode==0 and 'PASS: actual player startup/menu dispatch' in text and 'MENU PROBE FAILED' not in text,text
print('PASS: real up/down selection redraws and Enter paints the next menu with exact-game profile')
