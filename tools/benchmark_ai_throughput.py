"""Measure actual per-image/process and shared-model directory throughput on local assets."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import argparse
import json
import sys
import time

from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from ai_backend import upscale,upscale_many
from gpu_policy import inference_arguments
from runtime_assets.contracts import image_source_id


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('sources',type=Path)
    parser.add_argument('--count',type=int,default=12)
    parser.add_argument('--min-pixels',type=int,default=64)
    parser.add_argument('--max-pixels',type=int,default=4096)
    parser.add_argument('--include-fast-model',action='store_true')
    args=parser.parse_args()
    if not 2<=args.count<=32:parser.error('--count must be between 2 and 32')
    candidates=[]
    for path in args.sources.glob('*.png'):
        with Image.open(path) as image:
            area=image.width*image.height
            if args.min_pixels<=area<=args.max_pixels:candidates.append((area,path.name,path))
    candidates.sort()
    count=min(args.count,len(candidates))
    if count<2:raise RuntimeError('At least two images within the selected size range are required')
    selected=[candidates[round(i*(len(candidates)-1)/(count-1))][2] for i in range(count)]
    images=[]
    for path in selected:
        with Image.open(path) as image:images.append(image.convert('RGBA'))
    run=ROOT/'build'/('ai-throughput-'+str(time.time_ns()))
    run.mkdir(parents=True)
    report={'device':inference_arguments()[1],'sources':[
        {'file':p.name,'width':im.width,'height':im.height} for p,im in zip(selected,images)],'cases':{}}
    print('Device:',report['device'],'; sample:',count,'images; sizes:',[im.size for im in images],flush=True)
    warm=run/'warmup';warm.mkdir()
    upscale(images[0],warm,images[0].getchannel('A'))
    baseline=None
    cases=[('separate-process-1',1,None),('separate-process-5',5,None),
           ('shared-model-1',None,1),('shared-model-2',None,2),('shared-model-5',None,5)]
    if args.include_fast_model:cases.append(('animevideo-model-2',None,2))
    for name,workers,threads in cases:
        folder=run/name;folder.mkdir()
        started=time.perf_counter()
        if workers is not None:
            def convert(index):
                work=folder/str(index);work.mkdir()
                return upscale(images[index],work,images[index].getchannel('A'))
            with ThreadPoolExecutor(max_workers=workers) as pool:results=list(pool.map(convert,range(count)))
        else:
            options={'processing_threads':threads}
            if name.startswith('animevideo'):options['model']='realesr-animevideov3'
            results=upscale_many(images,folder,**options)
        for index,image in enumerate(results):image.save(folder/(str(index)+'.png'))
        elapsed=time.perf_counter()-started
        hashes=[image_source_id(image) for image in results]
        if baseline is None:baseline=hashes
        result={'seconds':round(elapsed,3),'images_per_second':round(count/elapsed,3),
                'matches_single_image_pixels':sum(a==b for a,b in zip(baseline,hashes)),
                'model':'realesr-animevideov3' if name.startswith('animevideo') else 'realesrgan-x4plus-anime'}
        report['cases'][name]=result
        (run/'results.json').write_text(json.dumps(report,indent=2))
        print(name,json.dumps(result),flush=True)
    print('Results:',run/'results.json',flush=True)


if __name__=='__main__':main()
