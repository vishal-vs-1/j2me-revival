"""Verify real shared-model scheduling and exact cache outputs in an isolated workspace."""
from pathlib import Path
import argparse
import json
import sys
import time

from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from runtime_assets.backends import NcnnBackend
from runtime_assets.contracts import image_source_id
from runtime_assets.service import AssetService


class CountedBackend(NcnnBackend):
    def __init__(self):
        super().__init__()
        self.batch_calls=0
        self.single_calls=0

    def enhance_many(self,sources,recipe,workdir):
        self.batch_calls+=1
        return super().enhance_many(sources,recipe,workdir)

    def enhance(self,source,recipe,workdir):
        self.single_calls+=1
        return super().enhance(source,recipe,workdir)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('sources',type=Path)
    parser.add_argument('benchmark',type=Path,help='results.json from benchmark_ai_throughput.py or profile_enhancement_devices.py')
    args=parser.parse_args()
    report=json.loads(args.benchmark.read_text())
    references=Path(report.get('reference_folder',str(args.benchmark.parent/'separate-process-1')))
    root=ROOT/'build'/('ai-batch-check-'+str(time.time_ns()))
    workspace=root/'check-game'
    originals=workspace/'original-assets';originals.mkdir(parents=True)
    ids=[]
    for row in report['sources']:
        with Image.open(args.sources/row['file']) as decoded:image=decoded.convert('RGBA')
        source_id=image_source_id(image)
        image.save(originals/(source_id+'.png'));ids.append(source_id)
    backend=CountedBackend();recipe=backend.recipe()
    service=AssetService(lambda selected:backend,poll_seconds=0.05)
    maximum=0
    started=time.perf_counter()
    try:
        service.register_game(workspace,recipe,game={'id':workspace.name},ai_recipe=recipe,paused=True)
        service.resume(workspace.name)
        deadline=time.monotonic()+90
        while time.monotonic()<deadline:
            stats=service.stats(workspace.name)
            maximum=max(maximum,stats['active_batch_images'])
            ready=workspace/'.runtime/ready'/(recipe.key+'.json')
            if stats['READY']==len(ids) and ready.is_file():break
            if stats['FAILED']:raise AssertionError(stats)
            time.sleep(0.05)
        else:raise AssertionError('Batch did not finish: '+str(service.stats(workspace.name)))
        assert backend.batch_calls==1 and backend.single_calls==0,(backend.batch_calls,backend.single_calls)
        assert stats['batch_fallbacks']==0,stats
        for index,source_id in enumerate(ids):
            output=workspace/'textures-cache'/recipe.key/(source_id+'.png')
            reference=references/(str(index)+'.png')
            with Image.open(output) as image,Image.open(reference) as baseline:
                assert image_source_id(image)==image_source_id(baseline),source_id
        result={'images':len(ids),'model_invocations':backend.batch_calls,
                'single_invocations':backend.single_calls,'maximum_inflight_images':maximum,
                'seconds':round(time.perf_counter()-started,3),'recipe_key':recipe.key,
                'matches_baseline':len(ids),'failures':stats['FAILED']}
        execution_report=workspace/'logs/last-conversion-gpu.json'
        if execution_report.is_file():result['execution']=json.loads(execution_report.read_text())
        (root/'results.json').write_text(json.dumps(result,indent=2))
        print('PASS: real GPU batch, independent cache outputs and unchanged recipe',result,flush=True)
        print('Results:',root/'results.json')
    finally:service.close()


if __name__=='__main__':main()
