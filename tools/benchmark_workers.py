"""Compare single/two-worker AI conversion on four imported Mr Bean images."""
from pathlib import Path
import json
import shutil
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from engine import Library
l=Library(); game=next(g for g in l.games() if 'Bean' in g['name'])
sources=sorted((l.workspace(game['id'])/'original-assets').glob('*.png'))[:4]
run=ROOT/'build'/('worker-benchmark-'+str(time.time_ns()))
results={}
for workers in [1,2]:
    folder=run/str(workers); (folder/'original-assets').mkdir(parents=True)
    assets=[]
    for source in sources:
        target=folder/'original-assets'/source.name; shutil.copy2(source,target); assets.append((source.stem,target))
    start=time.perf_counter()
    count=l.prepare_many(folder,assets,'ai',workers,print)
    results[str(workers)]={'seconds':round(time.perf_counter()-start,2),'images':count}
print(json.dumps(results,indent=2))
(run/'results.json').write_text(json.dumps(results,indent=2))
