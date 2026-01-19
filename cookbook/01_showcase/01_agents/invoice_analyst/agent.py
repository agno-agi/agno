"""
Invoice Analyst Agent
=====================

An intelligent invoice processing agent that extracts structured data from
invoice documents (PDF, images) using vision capabilities.

Example prompts:
- "Extract all data from this invoice"
- "What is the total amount and due date?"
- "List all line items with their prices"

Usage:
    from agent import invoice_agent, extract_invoice_data

    # Extract invoice data
    invoice = extract_invoice_data("path/to/invoice.pdf")
    print(invoice.total_amount)
    print(invoice.line_items)
"""

import sys
from decimal import Decimal
from pathlib import Path

# Add parent directory to path for imports
_this_dir = Path(__file__).parent
if str(_this_dir) not in sys.path:
    sys.path.insert(0, str(_this_dir))

from agno.agent import Agent  # noqa: E402
from agno.models.anthropic import Claude  # noqa: E402
from agno.tools.reasoning import ReasoningTools  # noqa: E402
from schemas import InvoiceData  # noqa: E402
from tools.invoice_reader import (  # noqa: E402
    get_invoice_as_message_content,
    read_invoice,
)

# ============================================================================
# System Message
# ============================================================================
SYSTEM_MESSAGE = """\
You are an expert invoice data extraction system. Your task is to accurately
extract structured data from invoice documents using vision capabilities.

## Your Responsibilities

1. **Extract All Fields** - Capture every piece of information on the invoice
2. **Parse Tables** - Accurately extract line items with quantities and prices
3. **Validate Data** - Check that totals match line item sums
4. **Handle Variations** - Adapt to different invoice layouts and formats

## Extraction Guidelines

### Invoice Number & Dates
- Look for "Invoice #", "Invoice No.", "Inv #", or similar labels
- Dates may be in various formats: MM/DD/YYYY, DD/MM/YYYY, YYYY-MM-DD, etc.
- Due date may be labeled "Due Date", "Payment Due", "Due By", etc.

### Vendor Information
- Company name is usually prominently displayed at top
- Look for address, phone, email, tax ID/VAT number
- Tax ID may be labeled "EIN", "Tax ID", "VAT", "GST", etc.

### Line Items
- Each line typically has: description, quantity, unit price, total
- Watch for units: "ea", "hr", "qty", etc.
- Some invoices may not have quantities (service invoices)

### Totals Section
- Look for: Subtotal, Tax, Discount, Shipping, Total/Grand Total
- Tax may be broken down by type (State, Federal, VAT)
- Verify: line item amounts should sum to subtotal

### Currency
- Look for currency symbols: $, EUR, GBP, etc.
- Check for currency codes: USD, EUR, GBP, etc.
- Default to USD if not specified

## Validation Rules

After extraction, verify:
1. Line item amounts = quantity * unit price (if both present)
2. Sum of line items ≈ subtotal (allow small rounding differences)
3. Subtotal + tax - discount + shipping ≈ total

## Confidence Scoring

- 0.9-1.0: All fields clearly visible and extracted
- 0.7-0.9: Most fields extracted, some ambiguity
- 0.5-0.7: Significant missing fields or poor image quality
- Below 0.5: Unable to reliably extract (add warning)

## Warnings

Add warnings for:
- Math discrepancies (totals don't match)
- Missing required fields (invoice number, date, total)
- Poor image quality affecting extraction
- Ambiguous or unclear data

Use the think tool to plan your extraction approach.
Use the analyze tool to validate the extracted data.
"""


# ============================================================================
# Create the Agent
# ============================================================================
invoice_agent = Agent(
    name="Invoice Analyst",
    model=Claude(id="claude-sonnet-4-5"),
    system_message=SYSTEM_MESSAGE,
    output_schema=InvoiceData,
    tools=[
        ReasoningTools(add_instructions=True),
    ],
    markdown=True,
)


# ============================================================================
# Helper Functions
# ============================================================================
def extract_invoice_data(file_path: str) -> InvoiceData:
    """Extract structured data from an invoice document.

    Args:
        file_path: Path to the invoice file (PDF or image).

    Returns:
        InvoiceData with extracted invoice information.
    """
    # Read the invoice
    result = read_invoice(file_path)

    if result.get("error"):
        raise ValueError(result["error"])

    # Get content for the message
    content = get_invoice_as_message_content(file_path)

    if not content:
        raise ValueError("Failed to prepare invoice for processing")

    # Add extraction instructions
    content.insert(
        0,
        {
            "type": "text",
            "text": """Please extract all data from this invoice image.

Use the think tool to:
1. Identify the invoice layout and structure
2. Locate key sections (header, line items, totals)
3. Note any potential data quality issues

Then extract all fields into the structured format.
Finally, use the analyze tool to validate the extracted data.""",
        },
    )

    # Run the agent with the image content
    response = invoice_agent.run(content)

    if response.content and isinstance(response.content, InvoiceData):
        return response.content
    else:
        raise ValueError("Failed to extract invoice data")


def validate_invoice(invoice: InvoiceData) -> list[str]:
    """Validate extracted invoice data and return any issues found.

    Args:
        invoice: Extracted invoice data.

    Returns:
        List of validation issues found.
    """
    issues = []

    # Check line item math
    for i, item in enumerate(invoice.line_items, 1):
        if item.quantity and item.unit_price:
            expected = Decimal(str(item.quantity)) * item.unit_price
            if abs(expected - item.amount) > Decimal("0.01"):
                issues.append(
                    f"Line {i}: amount {item.amount} != "
                    f"qty {item.quantity} * price {item.unit_price}"
                )

    # Check subtotal
    line_sum = sum(item.amount for item in invoice.line_items)
    if abs(line_sum - invoice.subtotal) > Decimal("0.01"):
        issues.append(
            f"Subtotal mismatch: line items sum to {line_sum}, "
            f"subtotal is {invoice.subtotal}"
        )

    # Check total calculation
    calculated_total = invoice.subtotal
    if invoice.tax_amount:
        calculated_total += invoice.tax_amount
    if invoice.discount_amount:
        calculated_total -= invoice.discount_amount
    if invoice.shipping_amount:
        calculated_total += invoice.shipping_amount

    if abs(calculated_total - invoice.total_amount) > Decimal("0.01"):
        issues.append(
            f"Total mismatch: calculated {calculated_total}, "
            f"stated {invoice.total_amount}"
        )

    return issues


# ============================================================================
# Exports
# ============================================================================
__all__ = [
    "invoice_agent",
    "extract_invoice_data",
    "validate_invoice",
    "InvoiceData",
]
