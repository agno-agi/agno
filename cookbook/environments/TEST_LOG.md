# Test Log: environments

Last run: 2026-07-19, live with `OPENAI_API_KEY`, `.venvs/demo/bin/python`.

### _01_first_env.py

**Status:** PASS

**Description:** The flagship: Env over two mental-math tasks, typed CodeScorer,
run_rollouts at k=8, the grid, summary() with fingerprints and learning-zone ids.

**Result:** 16 attempts, all scored, grid rendered, both fingerprints stamped
non-None. Note: the hard task sits at the edge of gpt-5.5's ability (7/8 on some
runs, 8/8 on others), so the learning zone is sometimes empty on this file's run --
the printed zone list reports whichever happened honestly.

---

### _02_export_sft.py

**Status:** PASS

**Description:** learning_zone() selection, to_sft_jsonl export, the report counters,
and the provenance sidecar.

**Result:** 24 attempts; t2 landed at 7/8 (learning zone), t1/t3 saturated at 8/8.
Exported 7 conversations to data/generated/train.jsonl, 1 failed attempt skipped,
sidecar written. The exported file was fed through the real external consumer loader
(rl-tutor TinkerTools._parse_conversations): 7 conversations parsed, no errors --
recorded in specs/agno/envs/notes/memory.md.

---

## 2026-07-19 — re-run after the review-fix commits (Claude + Codex review pass)

### _01_first_env.py

**Status:** PASS

**Description:** Live re-run against the fixed runner (manager nulling, secondary-model cache copies, validated factory products, default-model fingerprinting). Grid rendered, 16/16 scored, both fingerprints stamped, no warnings.

**Result:** Both tasks 8/8 this run, so the learning zone was empty (known behavior of a saturating fixed-arithmetic task; documented above).

### _02_export_sft.py

**Status:** PASS

**Description:** Live re-run, 24 attempts, no warnings or tracebacks. All three tasks 8/8, so the graceful empty-zone path fired and no train.jsonl was written this run; the export path itself is pinned by the unit suite (skip-order precedence, only_passed=False, sidecar).

**Result:** Clean exit through the empty-zone branch.

---

## 2026-07-19 — re-run after the second fix round (derived hermetic overrides, MCP guard, enumerated fingerprint)

### _01_first_env.py

**Status:** PASS

**Description:** Live re-run against the derived hermetic override set (culture read
rebind, session-summary/compression isolation, reasoning-agent recursion) and the
enumerated model-identity payload.

**Result:** 16/16 scored, grid rendered, both fingerprints stamped non-None under the
new payload. Both tasks 8/8 this run, learning zone empty (documented saturation
behavior).

### _02_export_sft.py

**Status:** PASS

**Description:** Live re-run, 24 attempts, no warnings or tracebacks.

**Result:** All three tasks 8/8, so the graceful empty-zone branch fired and no
train.jsonl was written this run; the export path (including the new ato_sft_jsonl
twin) is pinned by the unit suite.

---

## 2026-07-19 — three new use-case cookbooks (_03/_04/_05), all executed live

### _03_tool_reliability.py

**Status:** PASS

**Description:** ToolCallScorer over an order-support agent with a read-only lookup
tool; three tasks including a tempting-assertion trap (customer asserts a status in
the question) and an unknown-order id. Measures the fraction of attempts where the
lookup actually EXECUTED.

**Result:** 24 attempts in 26s, grounding rate 1.0 on every task — gpt-5.5 with
explicit grounding instructions executes the lookup on all 8 attempts of all three
tasks, including the trap and the not-found path.

### _04_judge_rubric.py

**Status:** PASS (after one documented calibration round)

**Description:** JudgeScorer in numeric mode (threshold 8) with a five-point support
rubric over a reply-rewriting agent. The file deliberately documents its own
iteration loop: the first-draft instructions ("be professional and empathetic")
measured 0/12 at threshold 8 with mean raw score ~5.2 (judge reasons: no
acknowledgment of frustration, no apology, no concrete next step); instructions were
tuned against the rubric and the run repeated.

**Result:** Before: 0/12, mean value 0.46. After: 12/12 in 45s, mean value 0.96. Both
endpoints recorded in the file's comments as the measured instructions-vs-rubric gap.

### _05_compare_models.py

**Status:** PASS (with one observed teardown artifact)

**Description:** EnvTask.from_jsonl over tasks/support_triage.jsonl (5 triage tasks,
one deliberately ambiguous), CodeScorer on a typed output_schema field, baseline run
on gpt-5.5, candidate via the model= override on gpt-5-mini, save/load round-trip,
and candidate.diff(baseline).

**Result:** 80 attempts total (40 + 40), both models 8/8 on all five tasks including
the ambiguous crash-then-charge row; baseline saved and reloaded; diff printed
"(env identical, policy changed)" with +0.00 on every row — the cheap-model question
answered "yes" for this task set. Observed: a RuntimeError("Event loop is closed")
traceback from httpcore transport cleanup between the two runs (exit code still 0) —
consistent with the known sync-door loop-shutdown residual and the unclosed
per-attempt HTTP clients noted in review.

---
