# Test Log -- 02_input_output




## Verification - 2026-08-20 round 4, focus areas (feat/v3.0, base ca5697ecd9)

**Environment:** `.venvs/demo/bin/python`, batch runner (240s timeout) + manual retries

| File | Status | Note |
|---|---|---|
| output_model.py | PASS |  |
| parser_model.py | PASS |  |

---

## Verification - 2026-08-18 round 3 (feat/v3.0, base b10e70d5d4)

**Environment:** `.venvs/demo/bin/python`, batch runner with 240s timeout

| File | Status | Note |
|---|---|---|
| input_schema.py | PASS | slow run (226s) with transient retries |
| streaming.py | PASS |  |

---

## Verification - 2026-08-18 (feat/v3.0)

**Environment:** `.venvs/demo/bin/python` | **Base Commit:** `b10e70d5d4` (feat/v3.0 merged)

### output_schema.py

**Status:** PASS

**Description:** Structured output via output_schema.

**Result:** Valid typed object returned and pretty-printed.

---

**Tested:** 2026-02-13
**Environment:** .venvs/demo/bin/python, pgvector: running

---

### expected_output.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates expected output. Ran successfully and produced expected output.
**Result:** Completed successfully in 4s.

---

### input_formats.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates input formats. Ran successfully and produced expected output.
**Result:** Completed successfully in 2s.

---

### input_schema.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates input schema. Ran successfully and produced expected output.
**Result:** Completed successfully in 101s.

---

### output_model.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates output model. Ran successfully and produced expected output.
**Result:** Completed successfully in 49s.

---

### output_schema.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates output schema. Ran successfully and produced expected output.
**Result:** Completed successfully in 18s.

---

### parser_model.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates parser model. Ran successfully and produced expected output.
**Result:** Completed successfully in 46s.

---

### response_as_variable.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates response as variable. Ran successfully and produced expected output.
**Result:** Completed successfully in 12s.

---

### save_to_file.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates save to file. Ran successfully and produced expected output.
**Result:** Completed successfully in 10s.

---

### streaming.py

**Status:** PASS
**Tier:** untagged
**Description:** Demonstrates streaming. Ran successfully and produced expected output.
**Result:** Completed successfully in 9s.

---
