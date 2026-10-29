"""Measure real device throughput, sampled GPU memory and host load without touching game caches."""
from __future__ import annotations

from pathlib import Path
import argparse
import ctypes as C
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time

from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from ai_backend import executable,_padded_rgb,_restore
from engine import enhance
from gpu_policy import devices
from runtime_assets.contracts import image_source_id
from tools.device_metrics import host_memory,process_sample,WindowsGpuCounters,NvidiaMetrics


def measure(command,folder,device,counters,nvidia,*,timeout=90,gpu_limit_mb=2048):
    baseline=nvidia.sample() if nvidia is not None else {}
    samples=[];reason=None;started=time.perf_counter()
    host_limit=min(1536,host_memory()['available_bytes']/1024**2*0.6)
    shared_limit=min(1024,host_memory()['available_bytes']/1024**2/3)
    with (folder/'process.log').open('w',encoding='utf-8') as log:
        process=subprocess.Popen(command,cwd=folder,stdout=log,stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)|getattr(subprocess,'BELOW_NORMAL_PRIORITY_CLASS',0))
        try:
            while process.poll() is None:
                sample=process_sample(process._handle)
                sample.update(counters.sample(process.pid))
                if nvidia is not None and device.get('kind')=='dedicated':
                    nv=nvidia.sample()
                    sample.update(nv_gpu_pct=nv.get('gpu_pct'),
                        nv_memory_extra_mb=max(0,nv.get('used_mb',0)-baseline.get('used_mb',0)))
                samples.append(sample)
                elapsed=time.perf_counter()-started
                if elapsed>timeout:reason='time limit'
                if (sample.get('host_peak_working_mb') or 0)>host_limit:reason='resident host memory budget'
                if host_memory()['available_bytes']<768*1024**2:reason='system RAM pressure'
                if device.get('kind')=='dedicated' and max(sample.get('dedicated',0),sample.get('nv_memory_extra_mb',0))>gpu_limit_mb:
                    reason='dedicated GPU memory budget'
                if device.get('kind')=='integrated' and sample.get('shared',0)>shared_limit:
                    reason='shared GPU memory budget'
                if reason:process.terminate();break
                time.sleep(0.05)
            process.wait(timeout=10)
            final=process_sample(process._handle)
            samples.append(final)
        finally:
            if process.poll() is None:process.kill();process.wait()
    elapsed=time.perf_counter()-started
    def peak(key):
        values=[sample[key] for sample in samples if sample.get(key) is not None]
        return round(max(values),2) if values else None
    util=[sample['nv_gpu_pct'] for sample in samples if sample.get('nv_gpu_pct') is not None]
    return {'seconds':elapsed,'returncode':process.returncode,'stopped_for':reason,
        'peak_dedicated_mb':peak('dedicated'),'peak_shared_mb':peak('shared'),
        'nvidia_peak_extra_mb':peak('nv_memory_extra_mb'),'peak_gpu_engine_pct':peak('engine'),
        'nvidia_average_gpu_pct':round(sum(util)/len(util),2) if util else None,
        'nvidia_peak_gpu_pct':max(util) if util else None,
        'peak_host_private_mb':peak('host_private_mb'),'peak_host_working_mb':peak('host_peak_working_mb'),
        'average_host_cpu_pct':round((final.get('cpu_seconds') or 0)/elapsed/(os.cpu_count() or 1)*100,2),
        'samples':len(samples)}


def prepare(folder,selected,stress=False):
    folder.mkdir(parents=True)
    images=[];paths=[]
    for index,path in enumerate(selected):
        with Image.open(path) as decoded:image=decoded.convert('RGBA')
        if stress:image=image.resize((512,512),Image.Resampling.NEAREST)
        target=folder/f'{index:04d}.png';_padded_rgb(image).save(target)
        images.append(image);paths.append(target)
    return images,paths


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('sources',type=Path)
    parser.add_argument('--count',type=int,default=256)
    parser.add_argument('--stress',action='store_true')
    parser.add_argument('--mode',choices=('all','small','stress','cpu'),default='all')
    parser.add_argument('--device-kinds',nargs='+',choices=('dedicated','integrated'),default=['dedicated','integrated'])
    parser.add_argument('--configs',help='Optional batch:processing-threads:tile-size configurations, comma separated')
    parser.add_argument('--worker-cpu',type=Path)
    args=parser.parse_args()
    args.sources=args.sources.resolve()
    if args.worker_cpu:
        configuration=json.loads(args.worker_cpu.read_text())
        start=time.perf_counter()
        for path in configuration['images']:
            with Image.open(path) as decoded:image=decoded.convert('RGBA')
            enhance(image).save(Path(configuration['output'])/Path(path).name)
        print('CPU pixel compute seconds',time.perf_counter()-start,flush=True)
        return
    if not 16<=args.count<=512:parser.error('--count must be between 16 and 512')
    candidates=[]
    for path in args.sources.glob('*.png'):
        with Image.open(path) as image:
            if 64<=image.width*image.height<=4096 and max(image.size)<=128:
                candidates.append((image.width*image.height,path.name,path))
    candidates.sort()
    count=min(args.count,len(candidates))
    if count<16:raise RuntimeError('At least 16 small source images are required')
    selected=[candidates[round(i*(len(candidates)-1)/(count-1))][2] for i in range(count)]
    run=ROOT/'build'/('device-profile-'+str(time.time_ns()));run.mkdir(parents=True)
    started=time.perf_counter();images,inputs=prepare(run/'small-input',selected)
    report={'host':host_memory(),'devices':devices(),'small_images':count,
            'sources':[{'file':path.name,'width':image.width,'height':image.height} for path,image in zip(selected,images)],
            'input_png_sha256':[hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs],
            'prepare_seconds':round(time.perf_counter()-started,3),'cases':[],'sample_interval_ms':50,
            'memory_note':'Per-process Windows GPU counters; NVIDIA total-allocation delta is recorded separately.'}
    print('Report:',run/'results.json',flush=True)
    print('Host:',report['host'],'Devices:',report['devices'],flush=True)
    try:counters=WindowsGpuCounters()
    except OSError as error:raise RuntimeError('GPU memory counters need Windows performance-counter access') from error
    try:nvidia=NvidiaMetrics()
    except OSError:nvidia=None
    reference={}
    try:
        for device in report['devices'] if args.mode in ('all','small') else []:
            if device['kind'] not in args.device_kinds:continue
            matrix=[(16,1,128),(64,1,128),(256,1,128),(256,2,128),
                    (256,4,128),(256,8,128),(256,4,256)]
            if device['kind']=='integrated':matrix=[(16,1,128),(64,1,128),(256,1,128),(256,2,128),(256,4,128)]
            if args.configs:
                matrix=[tuple(map(int,item.split(':'))) for item in args.configs.split(',')]
                if any(len(item)!=3 or not 1<=item[0]<=512 or not 1<=item[1]<=8 or item[2]<32 for item in matrix):
                    raise ValueError('Invalid profiling configuration')
            for batch,threads,tile in matrix:
                label=f"{device['kind']}-batch{batch}-proc{threads}-tile{tile}"
                print('Running:',label,flush=True)
                folder=run/label;folder.mkdir();parts=[];outputs=[]
                for start in range(0,count,batch):
                    group=folder/str(start);source=group/'input';output=group/'output'
                    source.mkdir(parents=True);output.mkdir()
                    for path in inputs[start:start+batch]:
                        try:os.link(path,source/path.name)
                        except OSError:shutil.copyfile(path,source/path.name)
                    command=[str(executable()),'-i',str(source),'-o',str(output),'-n','realesrgan-x4plus-anime',
                        '-m',str(executable().parent/'models'),'-s','4','-g',str(device['index']),
                        '-t',str(tile),'-j',f'1:{threads}:1']
                    result=measure(command,group,device,counters,nvidia)
                    parts.append(result)
                    if result['returncode'] or result['stopped_for']:break
                    outputs.extend(sorted(output.glob('*.png')))
                elapsed=sum(item['seconds'] for item in parts)
                hashes=[]
                if len(outputs)==count:
                    normalized=folder/'reference-rgba';normalized.mkdir()
                    for index,(path,image) in enumerate(zip(outputs,images)):
                        result=_restore(path,image,image.getchannel('A'))
                        hashes.append(image_source_id(result));result.save(normalized/(str(index)+'.png'))
                    if 'reference_folder' not in report:report['reference_folder']=str(normalized)
                if device['kind'] not in reference and hashes:reference[device['kind']]=hashes
                record={'label':label,'device':device,'workload':'small','images':len(hashes),
                    'completed':len(hashes)==count,'output_files':len(outputs),
                    'seconds':round(elapsed,3),'ms_per_image':round(elapsed/count*1000,3) if hashes else None,
                    'images_per_second':round(count/elapsed,2) if hashes else None,'processes':len(parts),
                    'stopped_for':next((p['stopped_for'] for p in parts if p['stopped_for']),None),
                    'pixel_matches':sum(a==b for a,b in zip(hashes,reference.get(device['kind'],[]))),
                    'peak_dedicated_mb':max((p['peak_dedicated_mb'] or 0 for p in parts),default=None),
                    'peak_shared_mb':max((p['peak_shared_mb'] or 0 for p in parts),default=None),
                    'nvidia_peak_extra_mb':max((p['nvidia_peak_extra_mb'] or 0 for p in parts),default=None),
                    'peak_host_private_mb':max((p['peak_host_private_mb'] or 0 for p in parts),default=None),
                    'peak_host_working_mb':max((p['peak_host_working_mb'] or 0 for p in parts),default=None),
                    'peak_gpu_engine_pct':max((p['peak_gpu_engine_pct'] or 0 for p in parts),default=None),
                    'nvidia_average_gpu_pct':round(sum((p['nvidia_average_gpu_pct'] or 0)*p['seconds'] for p in parts)/elapsed,2) if device['kind']=='dedicated' else None,
                    'nvidia_peak_gpu_pct':max((p['nvidia_peak_gpu_pct'] or 0 for p in parts),default=None) if device['kind']=='dedicated' else None,
                    'average_host_cpu_pct':round(sum(p['average_host_cpu_pct']*p['seconds'] for p in parts)/elapsed,2),
                    'parts':parts}
                report['cases'].append(record);(run/'results.json').write_text(json.dumps(report,indent=2))
                print(json.dumps({k:v for k,v in record.items() if k not in ('parts','device')}),flush=True)
        if args.stress or args.mode=='stress':
            stress_images,stress_inputs=prepare(run/'stress-input',selected[-4:],stress=True)
            stress_reference=None
            for device in report['devices']:
                if device['kind']!='dedicated':continue
                for threads,tile in [(1,128),(2,256),(1,512),(4,256)]:
                    folder=run/f"stress-{threads}-{tile}";folder.mkdir();output=folder/'output';output.mkdir()
                    command=[str(executable()),'-i',str(run/'stress-input'),'-o',str(output),'-n','realesrgan-x4plus-anime',
                        '-m',str(executable().parent/'models'),'-s','4','-g',str(device['index']),'-t',str(tile),'-j',f'1:{threads}:1']
                    result=measure(command,folder,device,counters,nvidia,timeout=60)
                    outputs=sorted(output.glob('*.png'));hashes=[]
                    if result['returncode']==0 and len(outputs)==4:
                        hashes=[image_source_id(_restore(path,image,image.getchannel('A'))) for path,image in zip(outputs,stress_images)]
                    if hashes and stress_reference is None:stress_reference=hashes
                    record={'label':folder.name,'device':device,'workload':'four-synthetic-512x512',
                        'completed':len(hashes)==4,'pixel_matches':sum(a==b for a,b in zip(hashes,stress_reference or [])),
                        'metrics':result}
                    report['cases'].append(record);(run/'results.json').write_text(json.dumps(report,indent=2))
                    print(json.dumps(record),flush=True)
        if args.mode in ('all','cpu'):
            folder=run/'cpu-pixel';folder.mkdir();output=folder/'output';output.mkdir()
            configuration=folder/'input.json'
            configuration.write_text(json.dumps({'images':[str(p.resolve()) for p in selected],'output':str(output)}))
            result=measure([sys.executable,str(Path(__file__).resolve()),str(args.sources),'--worker-cpu',str(configuration)],
                           folder,{'kind':'cpu'},counters,nvidia,timeout=60)
            report['cpu_fast_pixel']={'method':'CPU Scale2x, different quality from neural model','images':count,**result}
            (run/'results.json').write_text(json.dumps(report,indent=2));print('CPU Fast Pixel:',report['cpu_fast_pixel'],flush=True)
    finally:
        counters.close()
        if nvidia is not None:nvidia.close()
    print('Final report:',run/'results.json',flush=True)


if __name__=='__main__':main()
