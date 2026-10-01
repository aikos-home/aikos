"""Makes `aikos_transcriber` (and this folder's helpers) importable when the tests run from anywhere."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
for p in (HERE.parent, HERE):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
