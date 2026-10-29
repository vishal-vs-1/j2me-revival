"""Inspect imported games without running or rewriting their code."""
from pathlib import Path
import json,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from engine import Library
from game_inspection import inspect
library=Library()
for game in library.games():
    report=inspect(library.library/game['id']/'game.jar',game.get('assets'))
    out=library.workspace(game['id'])/'graphics-inspection.json';out.write_text(json.dumps(report,indent=2))
    print(game['name'],json.dumps(report,indent=2))
