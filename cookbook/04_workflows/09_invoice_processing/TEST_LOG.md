# TEST_LOG for cookbook/04_workflows/09_invoice_processing

### invoice_processing.py

**Status:** PASS

**Description:** Ran the workflow end to end with Claude Opus 5.5 (extractor) and GPT-5.6 (verifier) against:
- Sample PDF (slicedinvoices.com): INV-3337, 85.00 + 8.50 tax = 93.50. About 23s. Usually `approved`; one of four runs came back `corrected` with the same total, because the verifier flagged a small field difference.
- AWS invoice PDF served as `application/octet-stream` (raw.githubusercontent.com): byte sniffing detected the PDF. `approved`, 4 line items, total 4.11 USD.
- The sample invoice rendered to PNG and served locally: went through the image path, `approved` with the same fields as the PDF.
- Non-invoice PDF (w3.org dummy.pdf): `rejected`.
- HTML page (example.com): stopped at `fetch_invoice` with "not a PDF or image".
- 404 URL: stopped at `fetch_invoice` with the HTTP error.
- `not-a-url`: exits with "Not a valid URL" before the workflow runs.

Also tested `finalize` and `check_arithmetic` offline with hand-built step outputs, covering `approved`, `corrected`, `needs_review` (math mismatch, and an error with no fix), `rejected`, and a failed verifier step.

**Result:** All paths behave as expected. On the first run the verifier failed because OpenAI strict mode rejects `Field(description=...)` on nested model fields (`$ref cannot have keywords {'description'}`). `finalize` reported it as `needs_review`. Fixed by removing those descriptions.

---
