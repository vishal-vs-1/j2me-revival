"""Free offline inference, with alpha processed separately from RGB."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import numpy as np
from PIL import Image

ROOT=(Path(sys.executable).resolve().parent if getattr(sys,'frozen',False)
      else Path(__file__).resolve().parent)
MODEL='realesrgan-x4plus-anime'
SCALE=4
PADDING=8


def executable():
    return next((ROOT/'tools/ai').rglob('realesrgan-ncnn-vulkan.exe'),None)


def available():
    if executable() is None:return False
    try:
        from gpu_policy import devices
        return bool(devices())
    except (OSError,RuntimeError):return False


def _padded_rgb(image):
    a=np.array(image.convert('RGBA'))
    rgb=a[:,:,:3].copy(); valid=a[:,:,3]>0
    # The exact preprocessing is shared by individual and directory inference.
    for _ in range(PADDING):
        old=valid.copy(); colours=rgb.copy()
        for dy,dx in [(-1,0),(1,0),(0,-1),(0,1)]:
            shifted=np.roll(old,(dy,dx),(0,1))
            candidate=np.roll(colours,(dy,dx),(0,1))
            if dy==-1: shifted[-1,:]=False
            if dy==1: shifted[0,:]=False
            if dx==-1: shifted[:,-1]=False
            if dx==1: shifted[:,0]=False
            take=~valid & shifted
            rgb[take]=candidate[take]; valid[take]=True
    return Image.fromarray(np.pad(rgb,((PADDING,PADDING),(PADDING,PADDING),(0,0)),mode='edge'))


def _run(binary, source, output, workdir, *, model=MODEL, processing_threads=1, count=1):
    if isinstance(processing_threads,bool) or not isinstance(processing_threads,int) or not 1<=processing_threads<=8:
        raise ValueError('Inference processing threads must be between 1 and 8')
    from gpu_policy import inference_arguments
    gpu_args,device=inference_arguments()
    from runtime_assets.resources import current_budget,gpu_memory,ModelMemoryGuard,ResourcePressure
    budget=current_budget()
    if budget.reason:raise ResourcePressure(budget.reason)
    # Recheck at process start: another application may have consumed memory
    # since the scheduler admitted this group or Python prepared its inputs.
    processing_threads=min(processing_threads,budget.processing_threads)
    before=gpu_memory(device)
    process=subprocess.Popen([str(binary),'-i',str(source),'-o',str(output),'-s',str(SCALE),
                           '-n',model,'-m',str(binary.parent/'models'),'-t','128',
                           '-j',f'1:{processing_threads}:1',*gpu_args],
                          cwd=binary.parent,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,
                          creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)|getattr(subprocess,'BELOW_NORMAL_PRIORITY_CLASS',0))
    guard=ModelMemoryGuard(process,device,budget,baseline_used=before['used_bytes'] if before else None)
    guard.start()
    try:
        try:stdout,stderr=process.communicate(timeout=180*max(1,min(count,4)))
        except subprocess.TimeoutExpired:
            process.kill();process.communicate();raise
    finally:guard.close()
    if guard.reason:raise ResourcePressure(guard.reason)
    if process.returncode:
        raise RuntimeError('Local AI could not run on this GPU: '+stderr[-1200:])
    if device:
        import json,time,uuid
        report=Path(workdir)/'logs/last-conversion-gpu.json';report.parent.mkdir(parents=True,exist_ok=True)
        temporary=report.with_name('conversion-gpu-'+uuid.uuid4().hex+'.tmp')
        temporary.write_text(json.dumps({'device':device,'updated':time.time(),
            'model':model,'images':count,'processing_threads':processing_threads,
            'gpu_budget_bytes':budget.gpu_budget_bytes,'sampled_extra_gpu_bytes':guard.peak_extra_bytes},indent=2))
        os.replace(temporary,report)


def _restore(output, image, alpha):
    if not output.is_file():
        raise RuntimeError('Local AI did not produce the expected image: '+output.name)
    with Image.open(output) as decoded:
        expected=((image.width+PADDING*2)*SCALE,(image.height+PADDING*2)*SCALE)
        if decoded.size!=expected: raise ValueError('AI returned unexpected image dimensions')
        border=PADDING*SCALE
        enhanced=decoded.convert('RGBA').crop((border,border,border+image.width*SCALE,border+image.height*SCALE))
    if alpha.size != image.size:
        raise ValueError('Source transparency mask does not match the image dimensions')
    enhanced.putalpha(alpha.resize(enhanced.size, Image.Resampling.NEAREST))
    return enhanced


def upscale(image, workdir, alpha):
    binary=executable()
    if binary is None: raise RuntimeError('Select Install free AI first, or use Fast pixel enhancement.')
    with tempfile.TemporaryDirectory(prefix='inference-',dir=workdir) as temp:
        temp=Path(temp)
        source=temp/'input.png'; output=temp/'output.png'
        _padded_rgb(image).save(source)
        _run(binary,source,output,workdir)
        return _restore(output,image,alpha)


def upscale_many(images, workdir, *, processing_threads=1, model=MODEL):
    """Keep one model/GPU context for several independent, separately padded images."""
    images=list(images)
    if not images:return []
    if len(images)>512:raise ValueError('An inference batch is limited to 512 images')
    binary=executable()
    if binary is None: raise RuntimeError('Select Install free AI first, or use Fast pixel enhancement.')
    with tempfile.TemporaryDirectory(prefix='inference-batch-',dir=workdir) as temp:
        temp=Path(temp); source=temp/'input'; output=temp/'output'
        source.mkdir();output.mkdir()
        prepared=[]
        for index,image in enumerate(images):
            rgba=image.convert('RGBA')
            name=f'{index:04d}.png'
            _padded_rgb(rgba).save(source/name)
            prepared.append((name,rgba,rgba.getchannel('A')))
        _run(binary,source,output,workdir,model=model,
             processing_threads=processing_threads,count=len(prepared))
        return [_restore(output/name,image,alpha) for name,image,alpha in prepared]
