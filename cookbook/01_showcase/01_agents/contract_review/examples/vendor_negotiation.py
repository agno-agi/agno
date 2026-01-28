"""
Vendor Negotiation
==================

Generate redlines for a vendor contract from the buyer's perspective.

Usage:
    python examples/vendor_negotiation.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent import contract_agent  # noqa: E402
from agno.media import File  # noqa: E402

DOCS_DIR = Path(__file__).parent.parent / "documents"

if __name__ == "__main__":
    print("=" * 60)
    print("Contract Review Agent - Vendor Negotiation")
    print("=" * 60)
    print()

    contract_agent.print_response(
        "Generate redlines for this vendor contract. I'm the BUYER.\n"
        "For each problematic clause:\n"
        "1. Quote the original language\n"
        "2. Explain why it's unfavorable\n"
        "3. Provide specific replacement language\n"
        "4. Rate priority: MUST CHANGE vs NICE TO HAVE",
        files=[File(filepath=DOCS_DIR / "Sample_Vendor_Contract.pdf")],
        stream=True,
    )
