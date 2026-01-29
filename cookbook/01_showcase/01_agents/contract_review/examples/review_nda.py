"""
NDA Review
==========

Analyze an NDA from the Receiving Party's perspective.

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
        "I'm the Receiving Party in this NDA. Review it and:\n"
        "1. Identify all parties and their roles\n"
        "2. What information is considered confidential?\n"
        "3. How long does the confidentiality obligation last?\n"
        "4. Are there any one-sided terms that favor the Disclosing Party?\n"
        "5. What happens if I accidentally disclose something?",
        files=[File(filepath=DOCS_DIR / "sample_nda.txt")],
        stream=True,
    )
