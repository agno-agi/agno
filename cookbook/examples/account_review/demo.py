"""Run the interactive approval flow from the workflow guide."""

import runpy
from pathlib import Path

# ---------------------------------------------------------------------------
# Create the example
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Run the example
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    runpy.run_path(
        str(Path(__file__).with_name("account_review.py")), run_name="__main__"
    )
