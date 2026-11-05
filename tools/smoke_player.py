"""Launch the real demo MIDlet, check rendered output and terminate our test process."""
import json
from pathlib import Path
import subprocess
import sys
import time
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from engine import Library,locate_java

library=Library()
game=next(g for g in library.games() if g['name']=='Revival Demo')
folder=library.workspace(game['id'])
proof=ROOT/'build/player-proof.png'
if proof.exists(): proof.unlink()
log_path=ROOT/'build/player-smoke.log'
started=time.time()
process,log_path=library.launch(game,proof=proof)
try:
    while time.time()-started<40:
        time.sleep(1)
        if process.poll() is not None: raise RuntimeError(f'Player exited: {process.returncode}; see {log_path}')
        if proof.exists() and proof.stat().st_mtime>=started:
            text=log_path.read_text(encoding='utf-8',errors='replace')
            if 'PROOF:' in text:
                time.sleep(0.5)
                break
    else: raise RuntimeError(f'No 120-frame proof captured; see {log_path}')
    text=log_path.read_text(encoding='utf-8',errors='replace')
    assert 'Enhanced asset loaded:' in text,'No converted assets loaded'
    with Image.open(proof) as image:
        scale=game.get('render_scale',4)
        assert image.size==(game['width']*scale,game['height']*scale),image.size
        assert len(image.getcolors(2_000_000))>20,'Frame is empty or flat'
    metrics=json.loads(log_path.with_suffix('.stats.json').read_text())
    assert metrics['fps']>0 and metrics['scale']==scale,metrics
    if game.get('renderer','gpu')=='gpu':
        gpu=json.loads(Path(str(log_path.with_suffix('.stats.json'))+'.gpu.json').read_text())
        assert gpu['game_height']==gpu['window_height'],gpu
        assert abs(gpu['game_width']/gpu['game_height']-game['width']/game['height'])<.002,gpu
        assert metrics['backend']=='OpenGL GPU',metrics
        print('PASS: GPU device and desktop-height viewport:',gpu)
    print('PASS: actual MIDlet ran for 120 frames, loaded cached artwork and published frame/input metrics.',metrics)
finally:
    process.terminate()
    try: process.wait(timeout=5)
    except subprocess.TimeoutExpired: process.kill(); process.wait()
