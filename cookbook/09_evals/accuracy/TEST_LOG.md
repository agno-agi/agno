# Test Log: accuracy

> Results below distinguish live runs, mocked checks, and pending examples.

### accuracy_basic.py

**Status:** PENDING

**Description:** Runs sync and async calculator accuracy evaluations.

---

### accuracy_9_11_bigger_or_9_99.py

**Status:** PENDING

**Description:** Checks comparison accuracy for decimal values.

---

### accuracy_team.py

**Status:** PENDING

**Description:** Evaluates team routing accuracy for language handling.

---

### accuracy_with_given_answer.py

**Status:** PENDING

**Description:** Scores a manually provided answer against expected output.

---

### accuracy_with_tools.py

**Status:** PENDING

**Description:** Evaluates accuracy for factorial tool usage.

---

### db_logging.py

**Status:** PENDING

**Description:** Runs accuracy evaluation and stores results in PostgreSQL.

---

### evaluator_agent.py

**Status:** PENDING

**Description:** Uses a custom evaluator agent for accuracy scoring.

---

### accuracy_eval_metrics.py

**Status:** PASS

**Description:** Eval model metrics accumulated into agent run_output under "eval_model" detail key.

**Result:** Shows agent "model" tokens and "eval_model" tokens separately in metrics.details with full breakdown.

---

## Jev accuracy scorer — 2026-09-21

Validation used Windows, Python 3.12, and mocked provider responses. No live
TypeSafe or generative-model requests were made. These checks verify execution
and integration, not judgment quality or threshold calibration.

### jev_accuracy_with_given_answer.py

**Status:** PASS (mocked)

**Description:** Score a supplied paraphrase, incomplete answer, and contradiction
against one refund-policy reference using synchronous Jev calls.

**Result:** Three comparisons make three SDK requests and display the scores
through Rich `pprint`. No generative model is invoked.

### jev_accuracy_async.py

**Status:** PASS (mocked)

**Description:** Score the same answer categories concurrently with one scorer
and one native asynchronous SDK client.

**Result:** Three requests overlap, with one call per comparison. Results display
after completion and the client is reused.

### jev_accuracy_suite.py

**Status:** PASS (mocked)

**Description:** Evaluate a support agent against three references through the
suite CLI and `JevAccuracyScorer`.

**Result:** Three cases make exactly three generation calls and three async Jev
calls. The CLI exits successfully with mocked passing probabilities. Separate
suite tests verify reference forwarding, score fields, and error propagation.

### Scorer and regression checks

**Status:** PASS for new checks; one unrelated dependency failure in the broader run.

**Result:** All **52** new tests pass, including the three examples above and the
model-folder `accuracy_eval.py` introduction. Tests cover native sync/async clients,
Agent/Team outputs, structured values, instruction separation, exact thresholds,
invalid/missing data, malformed probabilities, SDK errors, metadata, fingerprints,
optional-dependency isolation, and suite behavior.

The combined scorer, eval, and Jev regression run reports **406 passed, 1 failed**.
The unchanged `test_real_mcp_close_swallows_a_delivered_cancel` fails importing
`MCPError`: the installed MCP package exposes `McpError` instead. Running that
test alone reproduces the same failure without the new scorer tests.

Ruff lint, formatting, and whitespace checks pass for the changed code.
The focused mypy check passes for `agno/scorer/typesafe.py` with the repository
configuration and `--follow-imports=silent`.

### jev_accuracy_suite.py — score display

**Status:** PASS (mocked)

**Description:** The suite renderer now displays custom score values and reasons
after each response, plus a Score column in the summary. Jev's reason exposes the
threshold decision without inventing a model explanation.

**Result:** All 33 focused CLI and cookbook checks pass, including values just
below and exactly at the threshold, readable literal markup in reasons, and one
generation/scoring call per case. Ruff lint and formatting pass. Initial sandbox
temporary-directory errors were resolved by rerunning with normal permissions.
No live provider calls were made for this display change.
