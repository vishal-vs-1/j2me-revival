"""Read/diagnose Mr Bean menu redraw using isolated copies; never change player settings."""
from pathlib import Path
import json,os,shutil,subprocess,sys,time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from engine import Library,locate_java

library=Library();game=next(g for g in library.games() if 'Bean' in g['name'])
pack=library.workspace(game['id']);out=ROOT/'build'/('menu-diagnosis-'+str(time.time_ns()));out.mkdir()
classpath=str(ROOT/'build/classes')+os.pathsep+str(ROOT/'tools/gpu/*')
subprocess.run([locate_java('javac'),'--release','8','-cp',classpath,'-d',str(ROOT/'build/classes'),str(ROOT/'tests/MenuControlProbe.java')],check=True)
results={}
for option in ['off','on']:
    folder=out/option;shutil.copytree(pack/'saves',folder)
    config=folder/'config/MrBeanRacer2/game.conf'
    text=config.read_text();text=text.replace('compatrepaintonsetcurrent:off','compatrepaintonsetcurrent:'+option)
    config.write_text(text)
    with (out/(option+'.log')).open('w') as log:
        process=subprocess.run([str(ROOT/'tools/runtime/bin/java.exe'),'--enable-native-access=ALL-UNNAMED','-Dfile.encoding=ISO_8859_1',
            '-Djme.gpu=true','-Djme.hidden=true','-Djme.stopSeconds=8','-Djme.scale=4',f'-Djme.pack={pack}',
            f'-Djme.textures={library.texture_dir(pack,game["backend"])}','-cp',classpath,'MenuControlProbe',
            str(library.library/game['id']/'game.jar'),'176','220','Mr Bean menu diagnosis'],cwd=folder,stdout=log,stderr=subprocess.STDOUT,timeout=18)
    lines=(out/(option+'.log')).read_text(errors='replace').splitlines()
    proof=[line for line in lines if line.startswith(('AFTER DOWN','AFTER UP','BEFORE ENTER','AFTER ENTER','AFTER EXPLICIT','MENU PROBE FAILED'))]
    print('FIRST REPAINT '+option+'\n'+'\n'.join(proof),flush=True)
    results[option]={'exit':process.returncode,'evidence':proof}
    assert process.returncode==0 and 'PASS: actual player startup/menu dispatch' in '\n'.join(lines),lines[-20:]
assert any('unchanged=true' in line for line in results['off']['evidence'])
assert any('unchanged=false' in line for line in results['on']['evidence'])
(out/'result.json').write_text(json.dumps(results,indent=2))
print('CONFIRMED: missing first repaint leaves the previous menu visible after Enter. Only isolated copies changed.')
print('Evidence:',out/'result.json')
