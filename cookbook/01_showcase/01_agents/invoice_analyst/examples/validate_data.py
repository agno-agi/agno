"""
Invoice Validation
==================

Demonstrates validating extracted invoice data.

This example shows:
- Extracting invoice data
- Running validation checks
- Identifying math discrepancies

Prerequisites:
    pip install pypdf pdf2image Pillow

Usage:
    python examples/validate_data.py <invoice_path>
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
_this_dir = Path(__file__).parent.parent
if str(_this_dir) not in sys.path:
    sys.path.insert(0, str(_this_dir))

from agent import extract_invoice_data, validate_invoice  # noqa: E402

# ============================================================================
# Invoice Validation Example
# ============================================================================
if __name__ == "__main__":
    # Get invoice path from command line or use default
    if len(sys.argv) > 1:
        invoice_path = sys.argv[1]
    else:
        invoices_dir = Path(__file__).parent.parent / "invoices"
        sample_invoices = list(invoices_dir.glob("*"))
        if sample_invoices:
            invoice_path = str(sample_invoices[0])
        else:
            print("Usage: python validate_data.py <invoice_path>")
            print("No sample invoices found in invoices/ directory")
            sys.exit(1)

    print("=" * 60)
    print("Invoice Analyst - Data Validation")
    print("=" * 60)
    print(f"Invoice: {invoice_path}")
    print()
    print("Extracting and validating...")
    print()

    try:
        # Extract invoice data
        invoice = extract_invoice_data(invoice_path)

        print("EXTRACTION RESULTS:")
        print("-" * 40)
        print(f"Invoice: {invoice.invoice_number}")
        print(f"Vendor: {invoice.vendor.name}")
        print(f"Total: {invoice.currency} {invoice.total_amount}")
        print(f"Line Items: {len(invoice.line_items)}")
        print(f"Extraction Confidence: {invoice.confidence_score:.0%}")
        print()

        # Run validation
        print("VALIDATION:")
        print("-" * 40)

        issues = validate_invoice(invoice)

        if not issues and not invoice.warnings:
            print("All validation checks passed!")
        else:
            if issues:
                print("Issues found:")
                for issue in issues:
                    print(f"  - {issue}")

            if invoice.warnings:
                print("Extraction warnings:")
                for warning in invoice.warnings:
                    print(f"  - {warning}")

        print()

        # Show detailed line item analysis
        print("LINE ITEM ANALYSIS:")
        print("-" * 40)

        for i, item in enumerate(invoice.line_items, 1):
            print(f"\nItem {i}: {item.description[:40]}...")

            if item.quantity and item.unit_price:
                calculated = item.quantity * item.unit_price
                match = "OK" if abs(calculated - item.amount) < 0.01 else "MISMATCH"
                print(f"  Qty: {item.quantity} x Price: {item.unit_price}")
                print(f"  Calculated: {calculated:.2f}")
                print(f"  Stated: {item.amount}")
                print(f"  Status: {match}")
            else:
                print(f"  Amount: {item.amount}")
                print("  (No qty/price breakdown)")

        # Summary
        print()
        print("TOTALS CHECK:")
        print("-" * 40)

        line_sum = sum(item.amount for item in invoice.line_items)
        print(f"Sum of line items: {line_sum}")
        print(f"Stated subtotal: {invoice.subtotal}")

        diff = abs(line_sum - invoice.subtotal)
        if diff < 0.01:
            print("Subtotal: OK")
        else:
            print(f"Subtotal: DIFFERENCE of {diff}")

    except Exception as e:
        print(f"Error: {e}")
