"""Locate packaged resources separately from the portable app's saved data."""
from pathlib import Path
import sys


FROZEN = bool(getattr(sys, 'frozen', False))
APP_ROOT = (Path(sys.executable).resolve().parent if FROZEN
            else Path(__file__).resolve().parent)
RESOURCE_ROOT = (Path(sys._MEIPASS).resolve() if FROZEN else APP_ROOT)
DATA_ROOT = APP_ROOT / 'data' if FROZEN else APP_ROOT
