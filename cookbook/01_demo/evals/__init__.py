"""Demo evals."""

import sys
from pathlib import Path

# Make the demo packages (agents, db, settings, teams, workflows)
# importable when this package is loaded from outside the cookbook
# directory, e.g. `python -m cookbook.01_demo.evals` from the repo
# root. Inside `cookbook/01_demo` this is a no-op.
_DEMO_DIR = Path(__file__).resolve().parents[1]
if str(_DEMO_DIR) not in sys.path:
    sys.path.insert(0, str(_DEMO_DIR))
