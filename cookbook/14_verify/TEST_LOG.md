# Verify Cookbooks Test Log

Last updated: 2026-08-21

## 2026-08-21: Initial pass

Environment: `.venv/bin/python` with `PYTHONPATH=libs/agno` (the demo venv was not present), model `gpt-5.5`
via `OpenAIResponses`, `OPENAI_API_KEY` from the shell. Every example ran once against the live model.

### 01_basics/verify_done.py

**Status:** PASS

**Description:** File-must-exist gate with a lazy prompt. Attempt 0 ended with no file and the verifier's string
was injected; attempt 1 wrote `report.md`.

**Result:** `status: verified`, `stop_reason: passed`, two attempts with distinct run_ids; attempt 0 FAIL,
attempt 1 PASS.

---

### 01_basics/unverified.py

**Status:** PASS

**Description:** An impossible check with `max_continuations=1`. Shows the unverified outcome, the per-attempt
run_ids and token counts, and that `output.status` still reads completed while the returned record says
unverified.

**Result:** `status: unverified`, `stop_reason: exhausted`, 2 attempts, 870 tokens summed across attempts,
`output.metadata["verification"]["status"] == "unverified"`.

---

### 02_shell/tests_must_pass.py

**Status:** PASS

**Description:** A scratch module with `add(a, b)` returning `a - b` and a failing pytest; `ShellVerifier`
running that pytest is the definition of done.

**Result:** pytest exit 1 before the agent ran; the agent fixed `calc.py` on attempt 0 and the verifier passed:
`status: verified`.

---

### 03_scorer/judge_gate.py

**Status:** PASS

**Description:** `ScorerVerifier(JudgeScorer(mode="numeric", threshold=8))` gating a limerick. The judge owns
the pass rule; its reason is the evidence the model reads.

**Result:** Attempt 0 scored 0.67 (the limerick omitted writes) and failed; attempt 1 scored 0.89 and passed:
`status: verified`.

---

### 04_predictions/verified_tool.py

**Status:** PASS

**Description:** A counter tool that silently caps each step at 5. The model predicts each result through
`expect`; one step call per message so each result is read before the next step is spent.

**Result:** Calls `(17, expect 17, got 5)`, `(5, 10, 10)`, `(5, 15, 15)`, `(2, 17, 17)`. The first call
diverged and the block was read before the second call was issued: the planned remaining steps were never spent
and the replan started from the real value 5; the model reported the cap. An earlier wording ("one step per
turn") made the model stop after a single step, which is why the instructions now say "one step call per
message".

---

### 05_fingerprints/noop_guard.py

**Status:** PASS

**Description:** An agent with no tools is asked to create a file in a scratch git repository;
`GitWorktreeFingerprint` plus `stop_on_noop=True`.

**Result:** `status: unverified`, `stop_reason: noop`, exactly 1 attempt; attempt 0's fingerprint equals the
baseline and `noop=True`. The model's reply was a shell command it did not have.

---
