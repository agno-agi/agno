# Test Log - _17_llm_as_judge

Tested 2026-07-18 against `gemini-3.5-flash`, agno 2.7.4.

### basic.py

**Status:** PASS

**Description:** Scores a (prompt, response) pair on overall quality 1-5 via `output_schema=Score` (bounded int, ge=1 le=5). Runs two samples against the same prompt: a correct one-sentence Rayleigh-scattering explanation and the non-answer "It just is."

**Result:** Detailed scattering answer scored `Score(overall=5)`; "It just is." scored `Score(overall=1)`. Both runs returned valid structured output on the first attempt.

---

### single_rubric.py

**Status:** PASS

**Description:** Scores a subscription-cancellation support answer against an explicit five-field rubric (correctness, completeness, clarity, concision, overall), each a bounded 1-5 int in `RubricScore`.

**Result:** Returned `RubricScore(correctness=5, completeness=5, clarity=5, concision=5, overall=5)` for the clear, complete cancellation instructions. All five fields populated independently in one structured response.

---

### with_rationale.py

**Status:** PASS

**Description:** Scores a project-name suggestion 1-5 and requires a one-sentence free-text rationale alongside the score, with instructions to quote a phrase from the response.

**Result:** Returned `overall=5` with rationale: "The suggested name 'Drift' is highly relevant and evocative for a sleep project, and the response provides helpful context regarding its domain availability." The rationale references the specific name 'Drift' as instructed.

---
