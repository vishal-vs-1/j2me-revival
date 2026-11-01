from pathlib import Path
import os,subprocess,sys,argparse
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from engine import locate_java,Library,runtime_arguments
from platform_support import java_binary_name
l=Library();g=next(g for g in l.games() if 'Bean' in g['name']);folder=l.workspace(g['id'])
classes=ROOT/'build/classes';out=ROOT/'build/mrbean-gpu';out.mkdir(exist_ok=True)
runtime_pack=out/'runtime-pack'
for name in ('original-assets','.runtime','logs','saves'):
    (runtime_pack/name).mkdir(parents=True,exist_ok=True)
classpath=str(classes)+os.pathsep+str(ROOT/'tools/gpu/*')+os.pathsep+str(ROOT/'vendor/freej2me-plus/resources')
parser=argparse.ArgumentParser();parser.add_argument('--runs',type=int,default=1)
parser.add_argument('--clean-startup',action='store_true',help='Exercise the optional verified wrapper removal')
parser.add_argument('--visible',action='store_true',help='Measure an active window as used during play')
args=parser.parse_args()
g=dict(g,remove_startup_wrappers=args.clean_startup)
# Select independently so a diagnostic never changes the user's saved startup preference.
from startup_cleaner import select_startup
playable,_=select_startup(l.library/g['id']/'game.jar',folder/'startup',enabled=args.clean_startup,
    javac=locate_java('javac'),player=ROOT/'build/jme-player.jar')
subprocess.run([locate_java('javac'),'--release','8','-cp',classpath,'-d',str(classes),
    str(ROOT/'tests/RuntimePreferencesFactory.java'),str(ROOT/'tests/GpuGameProbe.java')],check=True)
before={f.name for f in (runtime_pack/'original-assets').glob('*.png')}
for run in range(args.runs):
    logfile=out/f'probe-{run+1}.log'
    with logfile.open('w') as log:
        result=subprocess.run([str(ROOT/'tools/runtime/bin'/java_binary_name()),'--enable-native-access=ALL-UNNAMED','-Dfile.encoding=ISO_8859_1',
            '-Djava.util.prefs.PreferencesFactory=RuntimePreferencesFactory','-Djme.gpu=true','-Djme.scale=4',
            '-Dprobe.visible='+str(args.visible).lower(),'-Dprobe.directStartup='+str(args.clean_startup).lower(),
            *runtime_arguments(g['id']),f'-Djme.stats={out}/sample.stats.json',f'-Djme.pack={runtime_pack}',
            f'-Djme.textures={l.texture_dir(folder,g.get("backend","pixel"))}',
            '-cp',classpath,'GpuGameProbe',str(playable),str(out/'race.png')],cwd=out,stdout=log,stderr=subprocess.STDOUT,timeout=60)
    lines=logfile.read_text(errors='replace').splitlines()
    print('\n'.join(line for line in lines if line.startswith(('DEVICE','RACE','Steering','PASS','Game shutdown','GPU player','java.lang.','GAME STATE','STARTUP'))),flush=True)
    if result.returncode:print('\n'.join(lines[-35:]));raise SystemExit(result.returncode)
    after={f.name for f in (runtime_pack/'original-assets').glob('*.png')}
    print(f'Session {run+1}: {len(after-before)} new unique source images; '
          f'{len(after)} total content-addressed sources',flush=True)
    before=after
(out/'probe.log').write_text(logfile.read_text(errors='replace'))
print('PASS: runtime discoveries use the shared source cache and service')
