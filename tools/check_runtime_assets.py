"""Run headless Java contracts for generic runtime source capture and reuse."""
from pathlib import Path
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from engine import locate_java

classes = ROOT / 'build' / 'classes'
test_classes = ROOT / 'build' / 'runtime-asset-check-classes'
test_classes.mkdir(parents=True, exist_ok=True)
classpath = str(classes)
sources = [ROOT / 'tests' / name for name in (
    'RuntimeCaptureCheck.java', 'RuntimeTextureCheck.java', 'RuntimeObservationCheck.java')]
subprocess.run([locate_java('javac'), '--release', '8', '-cp', classpath,
                '-d', str(test_classes), *(str(path) for path in sources)], check=True)
for name in ('RuntimeCaptureCheck', 'RuntimeTextureCheck', 'RuntimeObservationCheck'):
    subprocess.run([locate_java(), '-cp', str(test_classes) + os.pathsep + classpath,
                    name, str(ROOT / 'build')], cwd=ROOT, check=True, timeout=30)
