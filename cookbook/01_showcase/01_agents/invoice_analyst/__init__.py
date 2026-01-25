"""
Invoice Analyst
===============

An intelligent invoice processing agent that extracts structured data
from invoice documents using vision capabilities.

Quick Start:
    from invoice_analyst import extract_invoice_data

    invoice = extract_invoice_data("invoice.pdf")
    print(invoice.total_amount)
    print(invoice.vendor.name)
    for item in invoice.line_items:
        print(f"  {item.description}: {item.amount}")
"""

from .agent import InvoiceData, extract_invoice_data, invoice_agent, validate_invoice
from .schemas import Address, LineItem, Vendor

__all__ = [
    "invoice_agent",
    "extract_invoice_data",
    "validate_invoice",
    "InvoiceData",
    "Vendor",
    "Address",
    "LineItem",
]
