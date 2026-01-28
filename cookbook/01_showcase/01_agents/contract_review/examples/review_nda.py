"""
NDA Review
==========

Basic NDA review - extract key terms and summarize.

Usage:
    python examples/review_nda.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent import contract_agent  # noqa: E402
from agno.media import File  # noqa: E402

DOCS_DIR = Path(__file__).parent.parent / "documents"

if __name__ == "__main__":
    print("=" * 60)
    print("Contract Review Agent - NDA Review")
    print("=" * 60)
    print()

    contract_agent.print_response(
        "Review this NDA and summarize the key terms.",
        files=[File(filepath=DOCS_DIR / "sample_nda.txt")],
        stream=True,
    )
