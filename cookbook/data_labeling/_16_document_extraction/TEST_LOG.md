# Test Log - _16_document_extraction

Tested 2026-07-18 against `gemini-3.5-flash`, agno 2.7.4.

### basic.py

**Status:** PASS

**Description:** Extracts document-level metadata (title, cuisine, language, recipe_count) from the public ThaiRecipes.pdf into a typed `RecipeBook` via `output_schema`. Exercises PDF file input by URL plus structured output on a Gemini model.

**Result:** Returned `RecipeBook(title='Thai SELECT Cookbook', cuisine='Thai', language='English', recipe_count=10)`. Single model call, 7449 total tokens, ~3.9s.

---

### with_confidence.py

**Status:** PASS

**Description:** Same metadata extraction with each field wrapped in a `ConfidentField` (value plus Literal high/medium/low confidence), exercising nested models and Literal enums inside the structured-output schema.

**Result:** All four fields populated with confidence "high": title 'Thai SELECT Cookbook', cuisine 'Thai', language 'English', recipe_count '10'. ~6.0s model call.

---

### with_line_items.py

**Status:** PASS

**Description:** Extracts book metadata plus a nested `List[Recipe]` (name, course, prep_time_minutes), the line-item extraction shape, from the same PDF.

**Result:** Returned title 'Thai SELECT COOKBOOK', cuisine 'Thai', and 10 recipes including 'Pad Thai Goong Sod' (prep 15), 'Tom Kha Gai' (prep 10), and 'Gluai Buat Chi' (prep 10); all `course` fields null, consistent with the document not labeling courses. ~9.4s model call.

---
