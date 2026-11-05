"""Focused CPU/GPU control profile wire and adapter checks."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from engine import locate_java


def main():
    classes = ROOT / "build" / "classes"
    gpu = ROOT / "tools" / "gpu"
    classpath = str(classes) + ";" + str(gpu / "*")
    checks = [
        ROOT / "tests" / "ControlProfileBindingsCheck.java",
        ROOT / "tests" / "AwtControlProfileInputCheck.java",
    ]
    subprocess.run([
        locate_java("javac"), "--release", "8", "-encoding", "UTF-8",
        "-cp", classpath, "-d", str(classes), *map(str, checks),
    ], check=True)
    fixture = ROOT / "tests" / "fixtures" / "control_profile_wire.txt"
    runtime_cp = str(classes) + ";" + str(gpu / "*")
    subprocess.run([
        locate_java(), "-Djava.awt.headless=true", "-cp", runtime_cp,
        "ControlProfileBindingsCheck", str(fixture),
    ], check=True)
    subprocess.run([
        locate_java(), "-Djava.awt.headless=true", "-cp", runtime_cp,
        "AwtControlProfileInputCheck", fixture.read_text(encoding="ascii").strip(),
    ], check=True)


if __name__ == "__main__":
    main()
