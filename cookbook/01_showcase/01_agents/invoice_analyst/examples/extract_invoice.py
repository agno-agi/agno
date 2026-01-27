"""
Single Invoice Extraction
=========================

Demonstrates extracting data from a single invoice.

This example shows:
- Loading an invoice document
- Extracting structured data
- Accessing vendor, line items, and totals

Prerequisites:
    pip install pypdf pdf2image Pillow

Usage:
    python examples/extract_invoice.py <invoice_path>
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
_this_dir = Path(__file__).parent.parent
if str(_this_dir) not in sys.path:
    sys.path.insert(0, str(_this_dir))

from agent import extract_invoice_data  # noqa: E402

# ============================================================================
# Single Invoice Extraction Example
# ============================================================================
if __name__ == "__main__":
    # Get invoice path from command line or use default
    if len(sys.argv) > 1:
        invoice_path = sys.argv[1]
    else:
        # Look for sample invoices
        invoices_dir = Path(__file__).parent.parent / "invoices"
        sample_invoices = list(invoices_dir.glob("*"))
        if sample_invoices:
            invoice_path = str(sample_invoices[0])
        else:
            print("Usage: python extract_invoice.py <invoice_path>")
            print("No sample invoices found in invoices/ directory")
            sys.exit(1)

    print("=" * 60)
    print("Invoice Analyst - Single Invoice Extraction")
    print("=" * 60)
    print(f"Invoice: {invoice_path}")
    print()
    print("Extracting...")
    print()

    try:
        invoice = extract_invoice_data(invoice_path)

        print("INVOICE DETAILS:")
        print("-" * 40)
        print(f"Invoice Number: {invoice.invoice_number}")
        print(f"Invoice Date: {invoice.invoice_date}")
        if invoice.due_date:
            print(f"Due Date: {invoice.due_date}")
        if invoice.po_number:
            print(f"PO Number: {invoice.po_number}")
        print()

        print("VENDOR:")
        print("-" * 40)
        print(f"Name: {invoice.vendor.name}")
        if invoice.vendor.address:
            addr = invoice.vendor.address
            parts = [
                p for p in [addr.street, addr.city, addr.state, addr.postal_code] if p
            ]
            if parts:
                print(f"Address: {', '.join(parts)}")
        if invoice.vendor.tax_id:
            print(f"Tax ID: {invoice.vendor.tax_id}")
        if invoice.vendor.email:
            print(f"Email: {invoice.vendor.email}")
        print()

        print(f"LINE ITEMS ({len(invoice.line_items)}):")
        print("-" * 40)
        for i, item in enumerate(invoice.line_items, 1):
            qty = f"x{item.quantity}" if item.quantity else ""
            price = f"@ {item.unit_price}" if item.unit_price else ""
            print(f"  {i}. {item.description} {qty} {price}")
            print(f"     Amount: {invoice.currency} {item.amount}")
        print()

        print("TOTALS:")
        print("-" * 40)
        print(f"Subtotal: {invoice.currency} {invoice.subtotal}")
        if invoice.tax_amount:
            rate = f" ({invoice.tax_rate}%)" if invoice.tax_rate else ""
            print(f"Tax{rate}: {invoice.currency} {invoice.tax_amount}")
        if invoice.discount_amount:
            print(f"Discount: -{invoice.currency} {invoice.discount_amount}")
        if invoice.shipping_amount:
            print(f"Shipping: {invoice.currency} {invoice.shipping_amount}")
        print(f"TOTAL: {invoice.currency} {invoice.total_amount}")
        print()

        if invoice.payment_terms:
            print(f"Payment Terms: {invoice.payment_terms}")
        if invoice.bank_details:
            print(f"Bank Details: {invoice.bank_details}")

        print()
        print(f"Confidence: {invoice.confidence_score:.0%}")

        if invoice.warnings:
            print()
            print("WARNINGS:")
            for warning in invoice.warnings:
                print(f"  - {warning}")

    except Exception as e:
        print(f"Error: {e}")
