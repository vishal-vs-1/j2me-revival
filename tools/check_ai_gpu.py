"""Exercise free local inference on both GPUs with explicit NCNN device IDs."""
from pathlib import Path
import sys,tempfile,json
from PIL import Image
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from ai_backend import upscale
from gpu_policy import settings,save_settings,devices
saved=settings();available=devices()
try:
    for mode in ['dedicated','integrated']:
        if not any(d['kind']==mode for d in available):continue
        save_settings(enhance_gpu=mode)
        with tempfile.TemporaryDirectory(dir=ROOT/'build') as folder:
            original=Image.new('RGBA',(8,8),(70,150,220,255));original.putpixel((2,2),(240,50,20,255))
            converted=upscale(original,Path(folder),Image.new('L',(32,32),255))
            assert converted.size==(32,32)
            report=json.loads((Path(folder)/'logs/last-conversion-gpu.json').read_text())
            assert report['device']['kind']==mode,report
            print(f"PASS: explicit conversion GPU {report['device']['index']}: {report['device']['name']}",flush=True)
finally:save_settings(**saved)
