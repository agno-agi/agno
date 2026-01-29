"""
Contract Review Agent Examples
==============================

Interactive examples demonstrating contract review capabilities.

Scenarios:
1. NDA Review - Analyze from Receiving Party perspective
2. Risk Assessment - Flag risks in a service agreement
3. Extract Obligations - Create compliance calendar from lease
4. Employment Review - Review job offer as employee
5. Vendor Negotiation - Generate redlines for vendor contract
6. Compare Contracts - Compare two contract versions

Run this file to see an interactive menu, or import individual scenarios.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent import contract_agent  # noqa: E402
from agno.media import File  # noqa: E402

DOCS_DIR = Path(__file__).parent.parent / "documents"


def scenario_1_nda_review():
    """Analyze an NDA from the Receiving Party's perspective."""
    print("\n" + "=" * 60)
    print("SCENARIO 1: NDA Review")
    print("=" * 60 + "\n")

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


def scenario_2_risk_assessment():
    """Perform a thorough risk assessment on a service agreement."""
    print("\n" + "=" * 60)
    print("SCENARIO 2: Risk Assessment")
    print("=" * 60 + "\n")

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


def scenario_3_extract_obligations():
    """Create a compliance calendar from a lease agreement."""
    print("\n" + "=" * 60)
    print("SCENARIO 3: Extract Obligations")
    print("=" * 60 + "\n")

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


def scenario_4_employment_review():
    """Review an employment agreement from the employee's perspective."""
    print("\n" + "=" * 60)
    print("SCENARIO 4: Employment Review")
    print("=" * 60 + "\n")

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


def scenario_5_vendor_negotiation():
    """Generate redlines for a vendor contract from the buyer's perspective."""
    print("\n" + "=" * 60)
    print("SCENARIO 5: Vendor Negotiation")
    print("=" * 60 + "\n")

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


def scenario_6_compare_contracts():
    """Compare two versions of a service agreement."""
    print("\n" + "=" * 60)
    print("SCENARIO 6: Compare Contracts")
    print("=" * 60 + "\n")

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


def show_menu():
    """Display interactive menu."""
    print("\n" + "=" * 60)
    print("Contract Review Agent - Examples")
    print("=" * 60)
    print("\nAvailable scenarios:")
    print("  1. NDA Review - Analyze from Receiving Party perspective")
    print("  2. Risk Assessment - Flag risks in service agreement")
    print("  3. Extract Obligations - Compliance calendar from lease")
    print("  4. Employment Review - Review job offer as employee")
    print("  5. Vendor Negotiation - Generate redlines")
    print("  6. Compare Contracts - Compare two versions")
    print("  7. Run all scenarios")
    print("  q. Quit")
    print()


def main():
    """Interactive example runner."""
    scenarios = {
        "1": scenario_1_nda_review,
        "2": scenario_2_risk_assessment,
        "3": scenario_3_extract_obligations,
        "4": scenario_4_employment_review,
        "5": scenario_5_vendor_negotiation,
        "6": scenario_6_compare_contracts,
    }

    while True:
        show_menu()
        choice = input("Select scenario (1-7, q to quit): ").strip().lower()

        if choice == "q":
            print("Goodbye!")
            break
        elif choice == "7":
            for fn in scenarios.values():
                fn()
        elif choice in scenarios:
            scenarios[choice]()
        else:
            print("Invalid choice. Please try again.")


if __name__ == "__main__":
    main()
