"""
Extract Obligations
===================

Extract deadlines and recurring obligations from a lease.

Usage:
    python examples/extract_obligations.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent import contract_agent  # noqa: E402
from agno.media import File  # noqa: E402

DOCS_DIR = Path(__file__).parent.parent / "documents"

if __name__ == "__main__":
    print("=" * 60)
    print("Contract Review Agent - Extract Obligations")
    print("=" * 60)
    print()

    contract_agent.print_response(
        "Extract all deadlines and recurring obligations from this lease.",
        files=[File(filepath=DOCS_DIR / "Sample_Lease_Agreement.pdf")],
        stream=True,
    )
