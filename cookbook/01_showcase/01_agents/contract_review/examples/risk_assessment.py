"""
Risk Assessment
===============

Perform a thorough risk assessment on a service agreement.

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
        "We're considering signing this service agreement as the CLIENT.\n"
        "Perform a thorough risk assessment:\n"
        "1. Flag ALL terms that are unfavorable to us\n"
        "2. Identify any unlimited liability exposure\n"
        "3. Check for auto-renewal traps\n"
        "4. Look for broad indemnification clauses\n"
        "5. Rate overall risk as LOW/MEDIUM/HIGH with justification\n"
        "6. For each high-risk item, suggest specific redline language.",
        files=[File(filepath=DOCS_DIR / "Risky_Service_Agreement.pdf")],
        stream=True,
    )
