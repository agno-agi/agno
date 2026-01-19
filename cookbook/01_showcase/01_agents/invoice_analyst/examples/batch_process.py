"""
Batch Invoice Processing
========================

Demonstrates processing multiple invoices.

This example shows:
- Processing multiple invoice files
- Aggregating results
- Handling errors gracefully

Prerequisites:
    pip install pypdf pdf2image Pillow

Usage:
    python examples/batch_process.py [invoices_directory]
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
_this_dir = Path(__file__).parent.parent
if str(_this_dir) not in sys.path:
    sys.path.insert(0, str(_this_dir))

from agent import extract_invoice_data, validate_invoice  # noqa: E402
from schemas import InvoiceData  # noqa: E402

# ============================================================================
# Batch Processing Example
# ============================================================================
if __name__ == "__main__":
    # Get directory from command line or use default
    if len(sys.argv) > 1:
        invoices_dir = Path(sys.argv[1])
    else:
        invoices_dir = Path(__file__).parent.parent / "invoices"

    if not invoices_dir.exists():
        print(f"Directory not found: {invoices_dir}")
        sys.exit(1)

    # Find all invoice files
    invoice_files = []
    for ext in ["*.pdf", "*.png", "*.jpg", "*.jpeg"]:
        invoice_files.extend(invoices_dir.glob(ext))

    if not invoice_files:
        print(f"No invoice files found in: {invoices_dir}")
        sys.exit(1)

    print("=" * 60)
    print("Invoice Analyst - Batch Processing")
    print("=" * 60)
    print(f"Directory: {invoices_dir}")
    print(f"Found {len(invoice_files)} invoice(s)")
    print()

    # Process each invoice
    results: list[tuple[str, InvoiceData | str]] = []

    for i, file_path in enumerate(invoice_files, 1):
        print(f"[{i}/{len(invoice_files)}] Processing: {file_path.name}")

        try:
            invoice = extract_invoice_data(str(file_path))
            results.append((file_path.name, invoice))

            print(f"    Invoice #: {invoice.invoice_number}")
            print(f"    Vendor: {invoice.vendor.name}")
            print(f"    Total: {invoice.currency} {invoice.total_amount}")
            print(f"    Confidence: {invoice.confidence_score:.0%}")

            # Quick validation
            issues = validate_invoice(invoice)
            if issues:
                print(f"    Warnings: {len(issues)}")

        except Exception as e:
            results.append((file_path.name, str(e)))
            print(f"    Error: {e}")

        print()

    # Summary
    print("=" * 60)
    print("BATCH SUMMARY")
    print("=" * 60)

    successful = [r for r in results if isinstance(r[1], InvoiceData)]
    failed = [r for r in results if isinstance(r[1], str)]

    print(f"Processed: {len(results)}")
    print(f"Successful: {len(successful)}")
    print(f"Failed: {len(failed)}")
    print()

    if successful:
        # Aggregate by vendor
        by_vendor: dict[str, list] = {}
        total_amount = 0

        for name, invoice in successful:
            if isinstance(invoice, InvoiceData):
                vendor_name = invoice.vendor.name
                if vendor_name not in by_vendor:
                    by_vendor[vendor_name] = []
                by_vendor[vendor_name].append(invoice)
                total_amount += float(invoice.total_amount)

        print("BY VENDOR:")
        print("-" * 40)
        for vendor, invoices in sorted(by_vendor.items()):
            vendor_total = sum(float(inv.total_amount) for inv in invoices)
            print(f"  {vendor}: {len(invoices)} invoice(s), ${vendor_total:,.2f}")

        print()
        print(f"GRAND TOTAL: ${total_amount:,.2f}")

    if failed:
        print()
        print("FAILED INVOICES:")
        print("-" * 40)
        for name, error in failed:
            print(f"  - {name}: {error}")
