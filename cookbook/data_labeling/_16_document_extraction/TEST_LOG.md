# Test Log - _16_document_extraction

Tested 2026-05-19 against `gemini-3.5-flash` (Gemini), agno 2.6.8.

### basic.py

**Status:** PASS

**Description:** Extract document-level metadata (title, cuisine, language, recipe_count) into a `RecipeBook`.

**Result:** Title "Thai SELECT Cookbook", cuisine "Thai cuisine", language "English", recipe_count 10.

---

### with_confidence.py

**Status:** PASS

**Description:** Same task with `ConfidentField` wrapping each value.

**Result:** All four fields populated with sensible confidences.

**Note:** Originally failed with `Invalid schema for response_format 'RecipeBook': $ref cannot have keywords {'description'}` — OpenAI's strict structured-output mode rejects a `description` on a field whose type is itself a referenced model. Fix: removed the `Field(..., description=...)` annotation on `recipe_count` (kept the explanatory text as a code comment).

---

### with_line_items.py

**Status:** PASS

**Description:** Extract a `RecipeBook` with a nested list of `Recipe` line items (name, course, prep time).

**Result:** Multiple recipes extracted with full nested structure.

---
