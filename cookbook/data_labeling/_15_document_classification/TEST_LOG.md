# Test Log - _15_document_classification

Tested 2026-05-22 against `gemini-3.5-flash`, agno 2.6.9.

### basic.py

**Status:** PASS

**Description:** Classify a PDF into one of {invoice, receipt, contract, spec_sheet, report, recipe, other}.

**Result:** Correctly classified as `recipe`.

---

### with_confidence.py

**Status:** PASS

**Description:** Same task with a `confidence` field.

**Result:** Classified as `recipe` with `high` confidence.

---
