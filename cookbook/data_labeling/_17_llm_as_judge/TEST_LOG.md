# Test Log - _17_llm_as_judge

Tested 2026-05-19 against `gemini-3.5-flash` (Gemini), agno 2.6.8.

Score schemas switched from `Literal[1, 2, 3, 4, 5]` to `int` with `ge=1, le=5`. Gemini's structured-output enforcement requires string-valued enums, not integer enums; bounded `int` keeps the same 1-5 scale and the discrete-output guarantee without the Literal incompatibility.

### basic.py

**Status:** PASS

**Description:** Score response quality on a 1-5 scale against the prompt.

**Result:** Detailed answer scored 5, "It just is." scored 1.

---

### single_rubric.py

**Status:** PASS

**Description:** Score against an explicit rubric (correctness, completeness, clarity, concision, overall).

**Result:** All rubric dimensions scored independently with a separate overall.

---

### with_rationale.py

**Status:** PASS

**Description:** Same task with a free-text rationale for the score.

**Result:** Score 4 with a rationale that calls out both the positives and a specific weakness.

---
