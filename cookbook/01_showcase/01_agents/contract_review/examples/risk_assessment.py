"""
Risk Assessment
===============

Flag potential risks in a contract.

Usage:
    python examples/risk_assessment.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent import contract_agent  # noqa: E402
from agno.media import File  # noqa: E402

DOCS_DIR = Path(__file__).parent.parent / "documents"

if __name__ == "__main__":
    print("=" * 60)
    print("Contract Review Agent - Risk Assessment")
    print("=" * 60)
    print()

    contract_agent.print_response(
        "Flag all potential risks in this contract. "
        "Focus on liability and indemnification clauses.",
        files=[File(filepath=DOCS_DIR / "Risky_Service_Agreement.pdf")],
        stream=True,
    )
