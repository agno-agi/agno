"""
Extract Obligations
===================

Create a compliance calendar from a lease agreement.

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
        "I just signed this commercial lease. Create a compliance calendar:\n"
        "1. List ALL deadlines I need to track (rent due, insurance renewals, etc.)\n"
        "2. Identify recurring obligations (monthly, quarterly, annual)\n"
        "3. What notice periods must I remember? (termination, renewal opt-out)\n"
        "4. Are there any conditions that trigger additional obligations?\n"
        "5. Format as a table: Obligation | Deadline/Frequency | Section Reference",
        files=[File(filepath=DOCS_DIR / "Sample_Lease_Agreement.pdf")],
        stream=True,
    )
