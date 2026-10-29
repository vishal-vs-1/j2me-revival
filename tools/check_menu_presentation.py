"""Original JAR + sustained menus + actual committed GPU frame latency."""
from pathlib import Path
import argparse, os, subprocess, sys, time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from engine import Library,locate_java,runtime_arguments
from startup_cleaner import MRBEAN
library=Library();game=next(g for g in library.games() if g['id']==MRBEAN);pack=library.workspace(game['id'])
parser=argparse.ArgumentParser();parser.add_argument('--hidden',action='store_true',
    help='Check function without foreground latency assertions');options=parser.parse_args()
out=ROOT/'build'/('menu-presentation-'+str(time.time_ns()));out.mkdir()
isolated_pack=out/'pack'
for name in ('original-assets','.runtime','logs','saves'):
    (isolated_pack/name).mkdir(parents=True,exist_ok=True)
cp=str(ROOT/'build/classes')+os.pathsep+str(ROOT/'tools/gpu/*')
subprocess.run([locate_java('javac'),'--release','8','-cp',cp,'-d',str(ROOT/'build/classes'),
    str(ROOT/'tests/RuntimePreferencesFactory.java'),str(ROOT/'tests/MenuPresentationProbe.java')],check=True,capture_output=True)
with (out/'check.log').open('w') as log:
    process=subprocess.run([str(ROOT/'tools/runtime/bin/java.exe'),'--enable-native-access=ALL-UNNAMED','-Dfile.encoding=ISO_8859_1',
        '-Djava.util.prefs.PreferencesFactory=RuntimePreferencesFactory',
        '-Djme.gpu=true','-Djme.hidden='+str(options.hidden).lower(),
        '-Dprobe.strictLatency='+str(not options.hidden).lower(),'-Djme.stopSeconds=40','-Djme.scale=4',
        *runtime_arguments(game['id']),f'-Djme.pack={isolated_pack}',f'-Djme.textures={library.texture_dir(pack,game["backend"])}',
        '-cp',cp,'MenuPresentationProbe',str(library.library/game['id']/'game.jar'),'176','220','Mr Bean presentation check'],
        cwd=out,stdout=log,stderr=subprocess.STDOUT,timeout=48)
text=(out/'check.log').read_text(errors='replace');print(text[-2400:])
assert process.returncode==0 and 'PASS: original wrapper' in text,text
