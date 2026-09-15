# Test Log - _15_document_classification

Tested 2026-07-18 against `gemini-3.5-flash`, agno 2.7.4.

### basic.py

**Status:** PASS

**Description:** Classifies a PDF (ThaiRecipes.pdf from agno-public S3) into one of {invoice, receipt, contract, spec_sheet, report, recipe, other} using a Literal-constrained Pydantic output_schema. Exercises File(url=...) PDF input and structured output on `google:gemini-3.5-flash`.

**Result:** Returned `Classification(label='recipe')` - correct label for the recipe PDF. This run: input=7449 tokens, output=6, duration 4.58s.

---

### with_confidence.py

**Status:** PASS

**Description:** Same classification task with an added `confidence` field (Literal high/medium/low) so downstream routing can escalate low-confidence documents. Exercises multi-field structured output over a PDF file input.

**Result:** Returned `Classification(label='recipe', confidence='high')` - correct label with high confidence. This run: input=7468 tokens, output=19, duration 3.03s.

---
