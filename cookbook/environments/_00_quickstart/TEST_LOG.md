# Test Log: environments

Last run: 2026-07-20, live with `OPENAI_API_KEY`, `.venvs/demo/bin/python`. All six
files executed end to end. Logs from the earlier build and fix rounds live in git
history.

### _01_first_env.py

**Status:** PASS

**Description:** Environment over two mental-math tasks, typed CodeScorer, run_rollouts at
k=8, the grid, summary() with fingerprints and learning-zone ids.

**Result:** 16 attempts in 55s, 16/16 scored, both fingerprints stamped non-None.
Both tasks 8/8 this run, so the learning zone was empty: the hard task sits at the
edge of gpt-5.5's ability (7/8 on some runs, 8/8 on others) and the printed zone
list reports whichever happened.

---

### _02_export_sft.py

**Status:** PASS

**Description:** learning_zone() selection, to_sft_jsonl export, the report
counters, and the provenance sidecar.

**Result:** 24 attempts in 103s, all three tasks 8/8, so the graceful empty-zone
branch fired and no train.jsonl was written this run. The export path itself
(skip-order precedence, only_passed=False, the sidecar, the ato_sft_jsonl twin) is
pinned by the unit suite, and an earlier live run's export was parsed clean by the
external rl-tutor loader (recorded in specs/agno/envs/notes/memory.md).

---

### _03_tool_reliability.py

**Status:** PASS

**Description:** ToolCallScorer over an order-support agent with a read-only lookup
tool; three tasks including a tempting-assertion trap and an unknown-order id.
Measures the fraction of attempts where the lookup actually executed. Ends with
print_report().

**Result:** 24 attempts in 21s, grounding rate 1.0 on every task including the trap
and the not-found path. All attempts passed, so print_report printed its one-line
all-clear.

---

### _04_judge_rubric.py

**Status:** PASS

**Description:** JudgeScorer in numeric mode (threshold 8) with a five-point
support rubric over a reply-rewriting agent, followed by print_report() for the
judge's reasons.

**Result:** 12 attempts in 40s, 12/12 at threshold 8, mean normalized value 0.95.
Two tasks landed in the learning zone (all attempts passed but raw judge scores
disagreed), which is the intended signal for a rubric with graded levels.

---

### _05_compare_models.py

**Status:** PASS (after restoring a file missing from the branch)

**Description:** Task.from_jsonl over tasks/support_triage.jsonl (5 triage
tasks, one deliberately ambiguous), CodeScorer on a typed output_schema field,
baseline on gpt-5.5, candidate via model= override on gpt-5-mini, save/load
round-trip, candidate.diff(baseline).

**Result:** First run FAILED with FileNotFoundError: tasks/support_triage.jsonl had
never been committed (an earlier session ran it from a local file that never made
it into git). The task set was reconstructed to the documented shape and checked
in; the re-run passed: 80 attempts (40 + 40) in 66s, baseline 1.0 on all five
tasks; the candidate dropped the ambiguous crash-then-charge row to 7/8, so the
diff printed a real "-0.12 regressed" line and "(env identical, policy changed)".
Baseline saved, reloaded, diffed — the cheap-model question answered "almost, and
here is the row to look at".

---

### _06_drilldown_demo.py

**Status:** PASS

**Description:** The closing example: same environment as _03, focused on reading
the evidence — errors(), print_report() (default and only="all" with attempts=2),
and print_attempt() for one full transcript — then the note on where this goes
next.

**Result:** 24 attempts in 20s, all passed. The report rendered per-attempt
verdicts, tool executions with parsed arguments, answers, and token counts; the
attempts=2 cap and the "... 6 more" elision worked; print_attempt rendered the
scorer verdict plus the full transcript via pprint_run_response.

---

### _07_support_triage.py

**Status:** NOT RUN LIVE (no API key in the authoring session)

**Description:** New cookbook: classify support tickets into buckets, k=8 per task,
surface the learning zone, export the passing runs. Written as the clean
"learning zone at a glance" screenshot example — one saturated task, two
deliberately ambiguous ones in the learning zone, one clear per remaining bucket.

**Result:** Syntax check passes; imports resolve against the current public API
(no stale Env/EnvTask names); the Environment constructs and the
scorer -> grid -> learning_zone() -> to_sft_jsonl wiring was exercised end-to-end
with a stub model (6 tasks, k=2, 12 scored — sound). The live model run was NOT
performed here because no OPENAI_API_KEY was available. Run it with a key to
produce the authentic grid (with duration + cost) for the screenshot:
`.venvs/demo/bin/python cookbook/environments/_07_support_triage.py`

---
