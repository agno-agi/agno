"""
Invoice Processing
==================

Turns an invoice URL (PDF or image) into verified, structured data.

The workflow has four steps:
1. fetch_invoice   - Download the URL once and check it is a PDF or image.
2. extract_invoice - Claude Opus reads the document into an `Invoice`.
3. verify_invoice  - GPT-5.6 re-reads the same document and audits the extraction.
4. finalize        - Plain Python applies the verifier's corrections, checks the
                     arithmetic, and returns a `ProcessedInvoice`.

Using two models from different providers means one model's misread is
likely to be caught by the other. The final arithmetic check needs no model
at all, so a total that does not add up is always flagged.

Key concepts:
- Workflow `input_schema` to validate the incoming URL
- Function steps that attach files for later agent steps
- Agent steps with `output_schema` for structured extraction
- Reading any earlier step's output with `step_input.get_step_content()`

Inputs to try:
- https://slicedinvoices.com/pdf/wordpress-pdf-invoice-plugin-sample.pdf
- Any public URL that serves an invoice PDF, PNG, JPEG or WEBP
"""

import sys
from typing import List, Literal, Optional

import httpx
from agno.agent import Agent
from agno.media import File, Image
from agno.models.anthropic import Claude
from agno.models.openai import OpenAIResponses
from agno.workflow.step import Step, StepInput, StepOutput
from agno.workflow.workflow import Workflow
from pydantic import BaseModel, Field, HttpUrl, ValidationError

MAX_INVOICE_BYTES = 20 * 1024 * 1024
# Absolute tolerance, in invoice currency, for arithmetic checks
AMOUNT_TOLERANCE = 0.02

SAMPLE_INVOICE_URL = (
    "https://slicedinvoices.com/pdf/wordpress-pdf-invoice-plugin-sample.pdf"
)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class InvoiceRequest(BaseModel):
    url: HttpUrl = Field(description="Public URL of the invoice (PDF or image)")


class Party(BaseModel):
    name: Optional[str] = Field(None, description="Company or person name")
    address: Optional[str] = Field(None, description="Full postal address")
    email: Optional[str] = None
    tax_id: Optional[str] = Field(None, description="VAT, GST, EIN or similar")


class LineItem(BaseModel):
    description: str
    quantity: Optional[float] = None
    unit_price: Optional[float] = None
    amount: float = Field(description="Line total as printed on the invoice")


class Invoice(BaseModel):
    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = Field(None, description="ISO 8601 date, YYYY-MM-DD")
    due_date: Optional[str] = Field(None, description="ISO 8601 date, YYYY-MM-DD")
    currency: Optional[str] = Field(None, description="ISO 4217 code, e.g. USD")
    # Nested models take no Field(description=...): OpenAI strict mode rejects it
    vendor: Party
    customer: Party
    line_items: List[LineItem]
    subtotal: Optional[float] = None
    discount: Optional[float] = Field(None, description="Total discount, positive")
    tax: Optional[float] = Field(None, description="Total tax amount")
    shipping: Optional[float] = None
    total: float = Field(description="Grand total as printed on the invoice")
    amount_paid: Optional[float] = None
    amount_due: Optional[float] = None
    payment_terms: Optional[str] = None
    notes: Optional[str] = None


class FieldIssue(BaseModel):
    field: str = Field(description="Dotted path, e.g. line_items.0.amount")
    extracted_value: Optional[str] = None
    correct_value: Optional[str] = None
    severity: Literal["error", "warning"]
    reason: str


class Verification(BaseModel):
    is_invoice: bool = Field(description="False if the document is not an invoice")
    issues: List[FieldIssue] = Field(description="Empty when the extraction is correct")
    # Full invoice with every issue fixed; null when there are no issues
    corrected_invoice: Optional[Invoice] = None


Status = Literal["approved", "corrected", "needs_review", "rejected"]


class ProcessedInvoice(BaseModel):
    source_url: str
    status: Status
    invoice: Optional[Invoice]
    issues: List[str]


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------
extractor = Agent(
    name="Invoice Extractor",
    model=Claude(id="claude-opus-5-5"),
    output_schema=Invoice,
    instructions=[
        "Extract the attached invoice into the response schema.",
        "Copy values exactly as printed. Never compute or guess a value that is not on the document.",
        "Leave a field null when the document does not show it.",
        "Write dates as YYYY-MM-DD and currencies as ISO 4217 codes.",
        "Amounts are plain numbers: no currency symbols or thousands separators.",
    ],
)

verifier = Agent(
    name="Invoice Verifier",
    model=OpenAIResponses(id="gpt-5.6"),
    output_schema=Verification,
    instructions=[
        "You audit invoice extractions. The input is JSON extracted from the attached document by another model.",
        "The attached document is the source of truth. Compare every field and line item against it.",
        "Report a field as an issue only when the document clearly shows a different value, or a value the extraction missed.",
        "Use severity 'error' for wrong amounts, numbers, dates or parties, and 'warning' for formatting or minor text differences.",
        "If there are issues, return corrected_invoice with every field filled in, not just the changed ones.",
        "If the document is not an invoice, set is_invoice to false.",
    ],
)


# ---------------------------------------------------------------------------
# Function Steps
# ---------------------------------------------------------------------------
def fetch_invoice(step_input: StepInput) -> StepOutput:
    request = step_input.input
    if not isinstance(request, InvoiceRequest):
        request = InvoiceRequest.model_validate(request)
    url = str(request.url)

    try:
        response = httpx.get(url, follow_redirects=True, timeout=30)
        response.raise_for_status()
    except httpx.HTTPError as e:
        return StepOutput(
            content=f"Could not download {url}: {e}", success=False, stop=True
        )

    data = response.content
    if len(data) > MAX_INVOICE_BYTES:
        return StepOutput(
            content=f"{url} is larger than 20 MB", success=False, stop=True
        )

    # Sniff the bytes: many hosts serve PDFs as application/octet-stream
    filename = url.rstrip("/").rsplit("/", 1)[-1] or "invoice"
    message = f"Extract the attached invoice. Source: {url}"
    if data.startswith(b"%PDF-"):
        pdf = File(content=data, mime_type="application/pdf", filename=filename)
        return StepOutput(content=message, files=[pdf])
    if data.startswith((b"\x89PNG", b"\xff\xd8\xff")) or data[8:12] == b"WEBP":
        return StepOutput(content=message, images=[Image(content=data)])

    return StepOutput(
        content=f"{url} is not a PDF or image (content-type: {response.headers.get('content-type')})",
        success=False,
        stop=True,
    )


def check_arithmetic(invoice: Invoice) -> List[str]:
    problems: List[str] = []

    def differs(a: float, b: float) -> bool:
        return abs(a - b) > AMOUNT_TOLERANCE

    for i, item in enumerate(invoice.line_items):
        if item.quantity is not None and item.unit_price is not None:
            expected = item.quantity * item.unit_price
            if differs(expected, item.amount):
                problems.append(
                    f"line_items.{i}: {item.quantity} x {item.unit_price} = {expected:.2f}, invoice says {item.amount:.2f}"
                )

    line_sum = sum(item.amount for item in invoice.line_items)
    if invoice.subtotal is not None and differs(line_sum, invoice.subtotal):
        problems.append(
            f"line items sum to {line_sum:.2f}, subtotal is {invoice.subtotal:.2f}"
        )

    base = invoice.subtotal if invoice.subtotal is not None else line_sum
    expected_total = (
        base - (invoice.discount or 0) + (invoice.tax or 0) + (invoice.shipping or 0)
    )
    if differs(expected_total, invoice.total):
        problems.append(
            f"computed total is {expected_total:.2f}, invoice total is {invoice.total:.2f}"
        )

    if invoice.amount_paid is not None and invoice.amount_due is not None:
        if differs(invoice.total - invoice.amount_paid, invoice.amount_due):
            problems.append(
                f"total {invoice.total:.2f} - paid {invoice.amount_paid:.2f} != amount due {invoice.amount_due:.2f}"
            )

    return problems


def finalize(step_input: StepInput) -> StepOutput:
    request = step_input.input
    if not isinstance(request, InvoiceRequest):
        request = InvoiceRequest.model_validate(request)
    source_url = str(request.url)

    extracted = step_input.get_step_content("extract_invoice")
    verification = step_input.get_step_content("verify_invoice")
    if not isinstance(extracted, Invoice) or not isinstance(verification, Verification):
        result = ProcessedInvoice(
            source_url=source_url,
            status="needs_review",
            invoice=extracted if isinstance(extracted, Invoice) else None,
            issues=["Extraction or verification did not return structured output"],
        )
        return StepOutput(content=result)

    if not verification.is_invoice:
        result = ProcessedInvoice(
            source_url=source_url,
            status="rejected",
            invoice=None,
            issues=["Verifier says the document is not an invoice"],
        )
        return StepOutput(content=result)

    corrected = verification.corrected_invoice if verification.issues else None
    invoice = corrected or extracted
    issues = [
        f"[{issue.severity}] {issue.field}: {issue.extracted_value!r} -> {issue.correct_value!r} ({issue.reason})"
        for issue in verification.issues
    ]
    math_problems = check_arithmetic(invoice)
    issues.extend(f"[math] {problem}" for problem in math_problems)

    status: Status
    has_errors = any(issue.severity == "error" for issue in verification.issues)
    if math_problems or (has_errors and corrected is None):
        status = "needs_review"
    elif verification.issues:
        status = "corrected"
    else:
        status = "approved"

    result = ProcessedInvoice(
        source_url=source_url, status=status, invoice=invoice, issues=issues
    )
    return StepOutput(content=result)


# ---------------------------------------------------------------------------
# Create Workflow
# ---------------------------------------------------------------------------
invoice_workflow = Workflow(
    name="Invoice Processing",
    description="Extract an invoice from a URL with one model, verify it with another, and return structured data",
    input_schema=InvoiceRequest,
    steps=[
        Step(name="fetch_invoice", executor=fetch_invoice),
        Step(name="extract_invoice", agent=extractor),
        Step(name="verify_invoice", agent=verifier),
        Step(name="finalize", executor=finalize),
    ],
)


# ---------------------------------------------------------------------------
# Run Workflow
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    invoice_url = sys.argv[1] if len(sys.argv) > 1 else SAMPLE_INVOICE_URL

    try:
        request = InvoiceRequest.model_validate({"url": invoice_url})
    except ValidationError:
        sys.exit(f"Not a valid URL: {invoice_url}")

    run = invoice_workflow.run(input=request)

    if isinstance(run.content, ProcessedInvoice):
        print(run.content.model_dump_json(indent=2))
    else:
        print(f"Workflow stopped: {run.content}")
