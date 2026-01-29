"""
Employment Review
=================

Review an employment agreement from the employee's perspective.

Usage:
    python examples/employment_review.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent import contract_agent  # noqa: E402
from agno.media import File  # noqa: E402

DOCS_DIR = Path(__file__).parent.parent / "documents"

if __name__ == "__main__":
    print("=" * 60)
    print("Contract Review Agent - Employment Review")
    print("=" * 60)
    print()

    contract_agent.print_response(
        "I received this employment offer. As the EMPLOYEE, review it for:\n"
        "1. Base salary and bonus structure - any clawback provisions?\n"
        "2. Non-compete clause - is it enforceable? What's the scope?\n"
        "3. IP assignment - do I retain rights to personal projects?\n"
        "4. Termination provisions - what's my severance?\n"
        "5. What should I try to negotiate before signing?",
        files=[File(filepath=DOCS_DIR / "Sample_Employment_Agreement.pdf")],
        stream=True,
    )
