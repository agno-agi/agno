"""
Compare Contracts
=================

Compare two versions of a service agreement.

Usage:
    python examples/compare_contracts.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent import contract_agent  # noqa: E402
from agno.media import File  # noqa: E402

DOCS_DIR = Path(__file__).parent.parent / "documents"

if __name__ == "__main__":
    print("=" * 60)
    print("Contract Review Agent - Compare Contracts")
    print("=" * 60)
    print()

    contract_agent.print_response(
        "Compare these two versions of a service agreement.\n"
        "1. What clauses were added, removed, or modified?\n"
        "2. Are the changes favorable or unfavorable to the client?\n"
        "3. Highlight any new risks introduced in version 2\n"
        "4. Which version would you recommend signing and why?",
        files=[
            File(filepath=DOCS_DIR / "Clean_Service_Agreement.pdf"),
            File(filepath=DOCS_DIR / "Risky_Service_Agreement.pdf"),
        ],
        stream=True,
    )
