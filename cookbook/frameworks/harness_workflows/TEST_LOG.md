# Test log: harness agents as workflow steps

### claude_step.py

**Status:** PASS (claude-sonnet-4-6 step, gpt-5.6-luna summary)

**Description:** A two-step workflow on a temporary copy of the sample project: Claude Code writes and runs a pytest test for the 100 dollar boundary, then an Agno writer summarises. A second run of the same session asks which test file was added and which subtotals it checks.

**Result:** Run 1: Claude created `test_shipping.py` with six cases, ran it (all passed), and the writer summarised in three lines. Run 2: Claude answered from its resumed conversation, naming `test_shipping.py` and the subtotals it checks, and the writer summarised that answer.

---

### parallel_review.py

**Status:** PASS (claude-sonnet-4-6 and gpt-5.6-luna reviewers, gpt-5.6-luna editor)

**Description:** Claude Code (read-only tools) and Codex (read-only sandbox) review `shipping.py` in a `Parallel`, listed directly as agents, then an Agno editor merges the reviews.

**Result:** Both reviewers completed in the parallel step, each with its own findings: fractional subtotals, booleans accepted as integers, non-numeric input and the zero-subtotal fee. The editor merged them into four findings attributed to Codex, Claude or both. No files were edited.

---

### loop_until_green.py

**Status:** PASS (claude-sonnet-4-6)

**Description:** A `Loop` with up to three iterations runs a Claude Code step on a workspace with a failing test (`shipping_fee(50) == 0`), ending once the step reports ALL TESTS PASS.

**Result:** Claude identified that the test contradicted the 100 dollar threshold, fixed the test (not `shipping.py`), re-ran pytest and reported ALL TESTS PASS, so the loop ended after one of three iterations. Resuming the conversation across iterations is covered by the unit tests.

---
