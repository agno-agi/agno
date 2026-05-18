# Test Log — cookbook/data_labeling

Test results for the data-labeling cookbook.

---

### pipeline.py (smoke test against ThaiRecipes.pdf)

**Status:** NOT YET RUN

**Description:** Single-document smoke test of the workflow. Runs both
labelers in parallel, then the reviewer, then conditionally the
adjudicator. Uses a public PDF that is not an invoice — the test only
verifies the wiring; all extracted fields should be null and the
labelers should report low confidence.

**Result:** Pending first run.

---

### run_batch.py (folder of invoices)

**Status:** NOT YET RUN

**Description:** Fans out the pipeline across every `.pdf` in
`data/invoices/` with `asyncio.Semaphore(16)`. Each document becomes a
session keyed by `invoice-<sha256[:16]>`. Records per-document status
and elapsed time.

**Result:** Pending first run.

---

### export.py (SQLite -> JSONL)

**Status:** NOT YET RUN

**Description:** Reads the `labeling_sessions` table from
`tmp/labeling.db`, walks each session's `runs` JSON, and emits one
warehouse-shaped row per invoice to `tmp/labels.jsonl`.

**Result:** Pending first run.

---
