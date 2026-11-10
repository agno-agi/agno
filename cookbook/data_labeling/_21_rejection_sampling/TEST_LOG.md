# Test Log - _21_rejection_sampling

Tested 2026-07-18 against `gemini-3.5-flash`, agno 2.7.4.

### basic.py

**Status:** PASS

**Description:** Teacher agent samples K=4 reasoning traces per problem for 6 math/code problems with hand-verified integer golds (all golds were also re-verified with a Python script before committing). A pure-code verifier keeps only traces whose final_answer equals the gold and writes them to data/generated/verified_traces.jsonl.

**Result:** Per-problem correct counts: p1 4/4, p2 4/4, p3 3/4 (one sample mis-traced the loop), p4 4/4, p5 4/4, p6 4/4. Printed "pass@4: 6/6 problems with at least one correct sample (1.00)" and "wrote 23 rows, kept 23, dropped 1 of 24 samples". JSONL re-read confirmed 23 rows with keys prompt/reasoning/final_answer/sample_index and all-integer final answers. Counts vary run to run; this is what this run observed.

---

### judge_gate.py

**Status:** PASS

**Description:** Best-of-N gate for 4 open-ended prompts with no programmatic verifier: generator (default temperature) samples N=3 candidates each, a temperature=0 Gemini judge scores them 1-5 against a constraint-checking rubric, and the argmax candidate is kept only if its score >= 4. Two prompts are deliberately adversarial (a 30-40 word paragraph with no letter 'e'; a grammatical 10-word all-'x' sentence).

**Result:** All four prompts printed scores [5, 5, 5] and were kept: "wrote 4 rows, kept 4 of 4 prompts, dropped 0". The drop path did not fire this run - and code-side verification showed the judge was right, not lenient: the lipogram candidate was a genuine 35-word paragraph with zero 'e' characters, and the all-'x' candidate was 10 real dictionary words each starting with 'x' ("Xylophagous, xenophobic, xanthic xenophobes xeroxed xeric, xylographic, xenolithic xylographs xenophobically."). Same-strength generator and judge saturate the 1-5 scale on short constrained prompts; this is recorded as a calibration note in the README.

---

### rl_prompt_selection.py

**Status:** PASS

**Description:** Teacher agent samples K=4 solutions per problem for 8 problems with hand-verified integer golds spanning designed-trivial (7 + 5) through designed-impossible (the 12345th prime, which cannot be sieved in-head). The same pure-code verifier computes per-problem pass rates; only prompts with 0 < correct < 4 are kept as RL training prompts in data/generated/rl_prompts.jsonl.

**Result:** Observed pass rates: r1 4/4, r2 4/4, r3 4/4, r4 (digit-sum count over 1..500) 4/4, r5 (60-step iterated map mod 1013) 4/4, r6 (613th prime) 4/4, r7 (exact 17-digit multiplication) 4/4, r8 (12345th prime) 2/4. Printed "kept 1 of 8 prompts (learning zone 0 < pass@4 < 1)" and "wrote 1 rows, dropped 7 always-solved, dropped 0 never-solved"; the kept row is {"prompt": "What is the 12345th prime number?", "gold": 132241, "pass_rate": 0.5}. Designed difficulty and observed difficulty diverged sharply: every designed-hard problem was solved 4/4 (the model does exact 17x17-digit multiplication in its reasoning), and the designed-impossible prompt landed mid-band because the model estimates the 12345th prime and hits it about half the time. Band membership is noisy at K=4: in an earlier run of an earlier problem set the 613th prime scored 2/4, and calibration probes scored the 60-step map 3/4 and the 12345th prime 1/4. Runtime was about 15 minutes, dominated by reasoning tokens on the hard problems.

---

### step_rewards.py

**Status:** PASS

**Description:** Math-Shepherd-style Monte-Carlo step scoring over the first 3 problems of basic.py's hand-verified gold set (imported, not duplicated). A solver writes one stepwise solution per problem (capped at 5 steps via instructions); each step prefix gets K=3 continuation rollouts from a default-temperature completer pinned to faithful continuation, and the step's score is the fraction of rollouts whose final_answer passes basic.py's pure-code verifier (integer equality to gold). p1's step 2 is a deliberately corrupted splice (72 - 15 miscomputed as 67). Rows {problem, steps, step_scores, k} go to data/generated/prm_rows.jsonl.

**Result:** Observed step scores (MC scores are observed-once; a rerun resamples both solutions and rollouts): p1 [1.00, 0.00, 1.00] - the printout flagged "first sharp drop at step 2 (1.00 -> 0.00) - reasoning breaks here" exactly at the corrupted step, with full recovery at step 3, which re-derives 57 * 5 = 285; p2 [1.00, 1.00, 1.00, 1.00]; p3 [1.00, 1.00, 1.00, 1.00, 1.00]; both uncorrupted solutions were flat at 1.00 and printed "no sharp drop". Printed "wrote 3 rows, scored 12 steps, ran 36 rollouts". JSONL re-read confirmed 3 rows with exactly the keys problem/steps/step_scores/k, len(steps) == len(step_scores) in every row, and k == 3. Completer faithfulness is load-bearing: an earlier run with a gentler continuation instruction ("build on the given steps; do not restart from scratch") scored the same corrupted step 0.67 because 2 of 3 rollouts repaired the arithmetic mid-flight; recorded as a calibration note in the README.

---
