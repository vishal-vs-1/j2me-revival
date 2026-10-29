"""Use the real launch path and native window cleanup with Mr Bean's recursive wrapper."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from engine import Library
library=Library();game=next(g for g in library.games() if 'Bean' in g['name'])
process,log=library.launch(game,stop_seconds=3,hidden=True)
try:
    code=process.wait(timeout=15)
    text=log.read_text(errors='replace')
    assert code==0,(code,text[-1500:])
    assert 'GPU player failed:' not in text,text[-1500:]
    assert 'GPU compositor:' in text,'GPU did not start'
    print('PASS: actual Mr Bean GPU player closes normally, including native cleanup; exit code 0')
finally:
    if process.poll() is None:process.kill();process.wait()
