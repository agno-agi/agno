"""
Contract Review Agent Examples
==============================
Interactive examples demonstrating contract review capabilities.

Scenarios:
1. Simple NDA Review (text file)
2. PDF Contract Review
3. Risky Contract Analysis
4. Employment Agreement

Run this file to see an interactive menu, or import individual scenarios.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent import contract_agent
from agno.media import File

DOCS_DIR = Path(__file__).parent.parent / "documents"


def scenario_1_simple_nda():
    """Review a simple NDA text file."""
    print("\n" + "=" * 60)
    print("SCENARIO 1: Simple NDA Review (Text)")
    print("=" * 60 + "\n")

    contract_agent.print_response(
        "Review this NDA and identify the key terms and any risks.",
        files=[File(filepath=DOCS_DIR / "sample_nda.txt")],
        stream=True,
    )


def scenario_2_pdf_nda():
    """Review an NDA PDF document."""
    print("\n" + "=" * 60)
    print("SCENARIO 2: PDF Contract Review")
    print("=" * 60 + "\n")

    contract_agent.print_response(
        "Analyze this NDA PDF and extract all obligations.",
        files=[File(filepath=DOCS_DIR / "Sample_NDA.pdf")],
        stream=True,
    )


def scenario_3_risky_contract():
    """Review a contract with intentional risks."""
    print("\n" + "=" * 60)
    print("SCENARIO 3: Risky Contract Analysis")
    print("=" * 60 + "\n")

    contract_agent.print_response(
        "Review this service agreement and flag ALL potential risks. "
        "Pay special attention to liability and indemnification clauses.",
        files=[File(filepath=DOCS_DIR / "Risky_Service_Agreement.pdf")],
        stream=True,
    )


def scenario_4_employment():
    """Review an employment agreement."""
    print("\n" + "=" * 60)
    print("SCENARIO 4: Employment Agreement")
    print("=" * 60 + "\n")

    contract_agent.print_response(
        "Analyze this employment agreement. Focus on compensation, "
        "termination provisions, and non-compete clauses.",
        files=[File(filepath=DOCS_DIR / "Sample_Employment_Agreement.pdf")],
        stream=True,
    )


def show_menu():
    """Display interactive menu."""
    print("\n" + "=" * 60)
    print("Contract Review Agent - Examples")
    print("=" * 60)
    print("\nAvailable scenarios:")
    print("  1. Simple NDA Review (text file)")
    print("  2. PDF Contract Review")
    print("  3. Risky Contract Analysis")
    print("  4. Employment Agreement")
    print("  5. Run all scenarios")
    print("  q. Quit")
    print()


def main():
    """Interactive example runner."""
    scenarios = {
        "1": scenario_1_simple_nda,
        "2": scenario_2_pdf_nda,
        "3": scenario_3_risky_contract,
        "4": scenario_4_employment,
    }

    while True:
        show_menu()
        choice = input("Select scenario (1-5, q to quit): ").strip().lower()

        if choice == "q":
            print("Goodbye!")
            break
        elif choice == "5":
            for fn in scenarios.values():
                fn()
        elif choice in scenarios:
            scenarios[choice]()
        else:
            print("Invalid choice. Please try again.")


if __name__ == "__main__":
    main()
