"""pytest bootstrap: put the pipeline engine root on sys.path so `pipeline`
and `run` import regardless of where pytest is invoked from."""

import os
import sys
from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parent.parent
if str(ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(ENGINE_ROOT))

# Keep the vendored AGI script scorer out of unit tests: it loads torch +
# a 1.3GB checkpoint and is exercised by explicit tests instead. Stage0
# honors this env override via agi_scorer.scorer_enabled().
os.environ.setdefault("AGI_SCORER_ENABLED", "0")
