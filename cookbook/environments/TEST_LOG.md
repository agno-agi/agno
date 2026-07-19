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
