"""pytest bootstrap: put the pipeline engine root on sys.path so `pipeline`
and `run` import regardless of where pytest is invoked from."""

import sys
from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parent.parent
if str(ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(ENGINE_ROOT))
