# Test Log - _05_text_pairwise_preference

Tested 2026-05-22 against `gemini-3.5-flash`, agno 2.6.9.

### basic.py

**Status:** PASS

**Description:** Pick winner between two responses to the same prompt; output A/B/tie.

**Result:** Picks the more informative response (A) over the trivial one (B).

---

### with_rationale.py

**Status:** PASS

**Description:** Same task with a free-text rationale for the choice.

**Result:** Winner and rationale agree; rationale cites the discriminating quality.

---

### with_rubric.py

**Status:** PASS

**Description:** Same task driven by an explicit rubric in the instructions.

**Result:** Picks the more accurate/complete response per the rubric.

---

### dpo_jury.py

**Status:** PASS

**Description:** Tested 2026-07-18 with `.venvs/demo` (agno 2.7.0a1) and against agno 2.7.3. A jury of 5 model families (gpt-5.5, claude-sonnet-5, gemini-3.5-flash, qwen/qwen3.6-27b via Groq, mistral-large-latest) labels 3 raw pairs and 3 gold pairs, scoring each pair in both orderings.

**Result:** 2 pairs accepted as DPO records (fib 5/5; git-reset 4/4 after the anthropic juror recused), is_even routed to human review (winner=tie, agreement 0.60), gold calibration 3/3. Occasional schema breaks from JSON-mode jurors and Mistral 429s on back-to-back runs are absorbed by the backoff retry in `ask`.

---
