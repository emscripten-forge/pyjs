# pytest config of the sync tests (run inside the browser by tests/main.py)
import sys
from pathlib import Path

# tests/ on sys.path: `from helpers import ...` (tests/main.py does that too)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
