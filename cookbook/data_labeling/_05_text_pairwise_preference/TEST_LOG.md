# Test Log - _05_text_pairwise_preference

Tested 2026-07-18 against `gemini-3.5-flash`, agno 2.7.4.

### basic.py

**Status:** PASS

**Description:** Pick the winner between two responses to the same prompt; typed A/B/tie output via output_schema.

**Result:** Returned `Preference(winner='A')`, preferring the substantive scattering explanation over "Because of physics."

---

### dpo_jury.py

**Status:** PASS

**Description:** A jury of 5 model families (gpt-5.5, claude-sonnet-5, gemini-3.5-flash, qwen/qwen3.6-27b via Groq, mistral-large-latest) labels 3 raw pairs and 3 gold pairs, scoring each pair in both orderings with position debiasing, self-preference recusal, gold calibration, and a 0.75 agreement gate.

**Result:** 2 DPO records emitted: fib (agreement 1.0, confidence 0.99, 5/5 votes for a) and git reset (agreement 1.0, confidence 0.99, 4/4 votes for a after the anthropic juror recused from the pair it authored). is_even routed to human review (winner=tie, agreement 0.60, confidence 0.83). Gold calibration 3/3. One juror emitted malformed JSON once ("Failed to convert response to output_schema" warning); the backoff retry in `ask` absorbed it.

---

### with_rationale.py

**Status:** PASS

**Description:** Same pairwise task with a one-sentence free-text rationale alongside the winner.

**Result:** Returned winner='A' ('Drift') with rationale: "Response A provides a realistic, evocative, and high-quality name suggestion with helpful context, whereas Response B is overly long and reads like a joke."

---

### with_rubric.py

**Status:** PASS

**Description:** Same pairwise task graded against an explicit 4-point ordered rubric (correctness, completeness, clarity, concision) in the instructions.

**Result:** Returned `Preference(winner='A')`, preferring the concrete Settings > Subscription cancellation steps over the vague "dig around in the app" response.

---
