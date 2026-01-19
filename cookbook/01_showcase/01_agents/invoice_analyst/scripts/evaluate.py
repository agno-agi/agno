"""
Evaluate Agent Accuracy
=======================

Runs validation tests on the invoice agent to verify extraction accuracy.

This is useful for:
- Regression testing after changes
- Validating extraction quality
- Benchmarking agent performance

Prerequisites:
    Run: python scripts/check_setup.py

Usage:
    python scripts/evaluate.py
"""

import sys
from pathlib import Path
from typing import Any

# Add parent directory to path for imports
_this_dir = Path(__file__).parent.parent
if str(_this_dir) not in sys.path:
    sys.path.insert(0, str(_this_dir))

from agent import validate_invoice  # noqa: E402

# ============================================================================
# Test Cases
# ============================================================================
# Note: Invoice analyst requires actual invoice files to test.
# This evaluate.py provides the framework - add test invoices to run real tests.


def create_mock_invoice():
    """Create a mock invoice for testing validation logic."""
    from decimal import Decimal

    from schemas import InvoiceData, LineItem, VendorInfo

    return InvoiceData(
        invoice_number="INV-001",
        invoice_date="2024-01-15",
        vendor=VendorInfo(
            name="Test Vendor Inc.",
            address="123 Test Street",
        ),
        line_items=[
            LineItem(
                description="Widget A",
                quantity=2,
                unit_price=Decimal("25.00"),
                amount=Decimal("50.00"),
            ),
            LineItem(
                description="Widget B",
                quantity=3,
                unit_price=Decimal("10.00"),
                amount=Decimal("30.00"),
            ),
        ],
        subtotal=Decimal("80.00"),
        tax_amount=Decimal("8.00"),
        total_amount=Decimal("88.00"),
        currency="USD",
        confidence=0.95,
    )


# ============================================================================
# Evaluation Functions
# ============================================================================
def test_validation_logic(verbose: bool = True) -> dict[str, Any]:
    """Test the invoice validation logic with a mock invoice."""
    if verbose:
        print("\n  Testing: validation_logic")
        print("  Description: Verify invoice math validation works correctly")

    try:
        # Test valid invoice
        valid_invoice = create_mock_invoice()
        issues = validate_invoice(valid_invoice)

        if len(issues) == 0:
            if verbose:
                print("  [PASS] Valid invoice passed validation")
            return {"name": "validation_logic", "passed": True}
        else:
            if verbose:
                print(f"  [FAIL] Valid invoice had issues: {issues}")
            return {"name": "validation_logic", "passed": False, "issues": issues}

    except Exception as e:
        if verbose:
            print(f"  [FAIL] Error: {e}")
        return {"name": "validation_logic", "passed": False, "error": str(e)}


def test_validation_catches_errors(verbose: bool = True) -> dict[str, Any]:
    """Test that validation catches math errors."""
    if verbose:
        print("\n  Testing: validation_catches_errors")
        print("  Description: Verify validation catches subtotal mismatch")

    try:
        from decimal import Decimal

        # Create invoice with wrong subtotal
        invalid_invoice = create_mock_invoice()
        invalid_invoice.subtotal = Decimal("100.00")  # Wrong! Should be 80.00

        issues = validate_invoice(invalid_invoice)

        if len(issues) > 0 and any("subtotal" in issue.lower() for issue in issues):
            if verbose:
                print("  [PASS] Validation caught subtotal mismatch")
            return {"name": "validation_catches_errors", "passed": True}
        else:
            if verbose:
                print("  [FAIL] Validation did not catch subtotal mismatch")
            return {"name": "validation_catches_errors", "passed": False}

    except Exception as e:
        if verbose:
            print(f"  [FAIL] Error: {e}")
        return {"name": "validation_catches_errors", "passed": False, "error": str(e)}


def run_evaluation(verbose: bool = True) -> dict[str, Any]:
    """Run all test cases and return summary."""
    if verbose:
        print("=" * 60)
        print("Invoice Analyst - Evaluation")
        print("=" * 60)
        print("\nRunning validation tests...")

    results = [
        test_validation_logic(verbose),
        test_validation_catches_errors(verbose),
    ]

    # Calculate summary
    passed = sum(1 for r in results if r["passed"])
    failed = len(results) - passed
    pass_rate = (passed / len(results)) * 100 if results else 0

    summary = {
        "total": len(results),
        "passed": passed,
        "failed": failed,
        "pass_rate": pass_rate,
        "results": results,
    }

    if verbose:
        print("\n" + "=" * 60)
        print("Summary")
        print("=" * 60)
        print(f"\n  Total:     {summary['total']}")
        print(f"  Passed:    {summary['passed']}")
        print(f"  Failed:    {summary['failed']}")
        print(f"  Pass Rate: {summary['pass_rate']:.1f}%")

        if failed > 0:
            print("\n  Failed tests:")
            for r in results:
                if not r["passed"]:
                    error = r.get("error", "See details above")
                    print(f"    - {r['name']}: {error}")

    return summary


# ============================================================================
# Main
# ============================================================================
if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("Invoice Analyst - Evaluation Suite")
    print("=" * 60)
    print(
        """
This script tests the invoice validation logic.

Note: Full invoice extraction tests require actual invoice files.
This script tests the validation helper functions.
"""
    )

    summary = run_evaluation(verbose=True)

    # Exit with appropriate code
    sys.exit(0 if summary["failed"] == 0 else 1)
