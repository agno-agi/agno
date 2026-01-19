# Invoice Analyst

An intelligent invoice processing agent that extracts structured data from invoice documents (PDF, images) using vision capabilities.

## What You'll Learn

| Concept | Description |
|:--------|:------------|
| **Vision Extraction** | Using LLM vision to understand document layouts |
| **Structured Output** | Extracting complex nested data (vendor, line items, totals) |
| **Data Validation** | Verifying extracted data for accuracy |
| **Document Processing** | Handling PDFs and images |

## Quick Start

### 1. Install Dependencies

```bash
pip install pypdf pdf2image Pillow
```

For PDF support, you also need poppler:

```bash
# macOS
brew install poppler

# Ubuntu
apt-get install poppler-utils
```

### 2. Run an Example

```bash
.venvs/demo/bin/python cookbook/01_showcase/01_agents/invoice_analyst/examples/01_extract_invoice.py path/to/invoice.pdf
```

## Examples

| # | File | What You'll Learn |
|:--|:-----|:------------------|
| 01 | `examples/01_extract_invoice.py` | Single invoice extraction |
| 02 | `examples/02_validate_data.py` | Validation and error checking |
| 03 | `examples/03_batch_process.py` | Processing multiple invoices |

## Architecture

```
invoice_analyst/
├── agent.py          # Main agent with vision processing
├── schemas.py        # Pydantic models for invoice data
├── tools/
│   └── invoice_reader.py  # PDF/image loading
├── invoices/         # Sample invoices (add your own)
└── examples/
```

## Key Concepts

### Vision-Based Extraction

The agent uses Claude's vision capabilities to understand invoice layouts without templates:

```python
from invoice_analyst import extract_invoice_data

invoice = extract_invoice_data("invoice.pdf")
print(invoice.vendor.name)
print(invoice.total_amount)
```

### Invoice Data Schema

```python
class InvoiceData(BaseModel):
    # Document Info
    invoice_number: str
    invoice_date: date
    due_date: Optional[date]
    po_number: Optional[str]

    # Parties
    vendor: Vendor
    bill_to: Optional[Address]
    ship_to: Optional[Address]

    # Line Items
    line_items: list[LineItem]

    # Totals
    subtotal: Decimal
    tax_amount: Optional[Decimal]
    discount_amount: Optional[Decimal]
    total_amount: Decimal
    currency: str

    # Metadata
    confidence_score: float
    warnings: list[str]
```

### Line Item Extraction

Each line item captures:

```python
class LineItem(BaseModel):
    description: str
    quantity: Optional[float]
    unit: Optional[str]
    unit_price: Optional[Decimal]
    amount: Decimal
```

### Validation

Built-in validation checks:

```python
from invoice_analyst import extract_invoice_data, validate_invoice

invoice = extract_invoice_data("invoice.pdf")
issues = validate_invoice(invoice)

if issues:
    for issue in issues:
        print(f"Warning: {issue}")
```

Validation includes:
- Line item math (qty * price = amount)
- Subtotal verification (sum of line items)
- Total calculation (subtotal + tax - discount)

## Supported Formats

| Format | Extension | Notes |
|:-------|:----------|:------|
| PDF | `.pdf` | Requires poppler for conversion |
| PNG | `.png` | Direct processing |
| JPEG | `.jpg`, `.jpeg` | Direct processing |

## Usage Patterns

### Basic Extraction

```python
from invoice_analyst import extract_invoice_data

invoice = extract_invoice_data("invoice.pdf")

print(f"Invoice #{invoice.invoice_number}")
print(f"Vendor: {invoice.vendor.name}")
print(f"Total: {invoice.currency} {invoice.total_amount}")

for item in invoice.line_items:
    print(f"  - {item.description}: {item.amount}")
```

### With Validation

```python
from invoice_analyst import extract_invoice_data, validate_invoice

invoice = extract_invoice_data("invoice.pdf")

# Check for issues
issues = validate_invoice(invoice)
if issues:
    print("Validation issues found:")
    for issue in issues:
        print(f"  - {issue}")

# Check extraction warnings
if invoice.warnings:
    print("Extraction warnings:")
    for warning in invoice.warnings:
        print(f"  - {warning}")
```

### Batch Processing

```python
from pathlib import Path
from invoice_analyst import extract_invoice_data

invoices_dir = Path("invoices/")
for invoice_file in invoices_dir.glob("*.pdf"):
    try:
        invoice = extract_invoice_data(str(invoice_file))
        print(f"{invoice_file.name}: {invoice.total_amount}")
    except Exception as e:
        print(f"{invoice_file.name}: Error - {e}")
```

## Confidence Scores

The agent provides a confidence score (0-1) for each extraction:

| Score | Meaning |
|:------|:--------|
| 0.9-1.0 | All fields clearly visible and extracted |
| 0.7-0.9 | Most fields extracted, some ambiguity |
| 0.5-0.7 | Significant missing fields or poor quality |
| < 0.5 | Unable to reliably extract |

## Requirements

- Python 3.11+
- Anthropic API key
- poppler (for PDF support)

## Environment Variables

```bash
export ANTHROPIC_API_KEY=your-anthropic-key
```

## Adding Sample Invoices

Place your invoice files in the `invoices/` directory:

```
invoices/
├── invoice_001.pdf
├── invoice_002.png
└── receipt.jpg
```

Then run the examples to process them.
