# 04_workflows/09_invoice_processing

Turn an invoice URL (PDF or image) into verified, structured data.

## How it works

| Step | Type | What it does |
|------|------|--------------|
| `fetch_invoice` | Function | Downloads the URL once, sniffs the bytes for PDF/PNG/JPEG/WEBP, and attaches the document for later steps. Stops the workflow on a bad download or unsupported file. |
| `extract_invoice` | Agent (Claude Opus 5.5) | Reads the document into an `Invoice` schema. |
| `verify_invoice` | Agent (GPT-5.6) | Re-reads the same document, audits every field, and returns a corrected invoice if anything is wrong. |
| `finalize` | Function | Applies corrections, checks the arithmetic (line items, subtotal, tax, total, amount due), and returns a `ProcessedInvoice`. |

The extractor and verifier come from different providers, so one model's misread is likely to be caught by the other. The arithmetic check is plain Python, so a total that does not add up is always flagged.

The result has a `status`:
- `approved`: the verifier found no issues and the math checks out
- `corrected`: the verifier fixed fields and the corrected invoice's math checks out
- `needs_review`: math does not add up, or the verifier found errors without a fix
- `rejected`: the document is not an invoice

## Run

```bash
export ANTHROPIC_API_KEY=...
export OPENAI_API_KEY=...

# Sample invoice
.venvs/demo/bin/python cookbook/04_workflows/09_invoice_processing/invoice_processing.py

# Your own invoice
.venvs/demo/bin/python cookbook/04_workflows/09_invoice_processing/invoice_processing.py https://example.com/invoice.pdf
```

From code:

```python
from invoice_processing import InvoiceRequest, invoice_workflow

run = invoice_workflow.run(input=InvoiceRequest(url="https://example.com/invoice.pdf"))
print(run.content.model_dump_json(indent=2))
```

## Notes
- Nested models in the schemas have no `Field(description=...)`. OpenAI strict mode rejects a description next to a `$ref`.
- Swap either model by changing the `model=` on `extractor` or `verifier`. Keep them on different providers to get an independent second opinion.
