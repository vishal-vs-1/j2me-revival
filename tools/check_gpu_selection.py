"""Verify actual OpenGL devices for both GPU classes using the real player launch path."""
from pathlib import Path
import sys,json
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from engine import Library
from gpu_policy import settings,save_settings,devices,player_java
saved=settings();library=Library();game=next(g for g in library.games() if g['name']=='Revival Demo')
available=devices();print('Devices:',available)
try:
    for mode in ['auto','integrated']:
        if mode=='integrated' and not any(d['kind']=='integrated' for d in available):continue
        save_settings(render_gpu=mode)
        process,log=library.launch(game,stop_seconds=3,hidden=True)
        try:
            code=process.wait(timeout=15)
            assert code==0,(code,log.read_text(errors='replace')[-1000:])
            report=json.loads(Path(str(log.with_suffix('.stats.json'))+'.gpu.json').read_text())
            print(mode,report['device'],flush=True)
            assert report['matched'],report
            if mode=='auto' and any(d['kind']=='dedicated' for d in available):assert report['expected']==next(d['name'] for d in available if d['kind']=='dedicated')
        finally:
            if process.poll() is None:process.kill();process.wait()
    print('PASS: actual OpenGL dedicated-first selection and integrated switching')
finally:
    save_settings(**saved);player_java(saved['render_gpu'])
