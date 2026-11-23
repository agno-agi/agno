# Test Log - _19_inter_annotator_agreement

Tested 2026-07-18 against `gemini-3.5-flash`, agno 2.7.4.

### basic.py

**Status:** PASS

**Description:** Three instruction framings (terse, detailed rubric, shopper persona) of one sentiment guideline label 12 texts, 4 designed to be ambiguous (sarcasm, balanced mix, faint praise, ambivalence). self_check() asserts all four stdlib metric implementations against a perfect-agreement matrix (all 1.0) and a hand-derived 2x4 matrix (raw 0.5, Cohen 0.0, Fleiss 0.0, alpha 0.125) before any model call. Non-unanimous items are routed to a printed review list.

**Result:** self_check passed. Metrics this run: raw_agreement 0.833, fleiss_kappa 0.742, krippendorff_alpha 0.749, cohen_kappa terse_vs_rubric 0.874, terse_vs_persona 0.739, rubric_vs_persona 0.629. Exactly the 3 designed-ambiguous items disagreed and were routed to review (mixed: terse=negative/rubric=neutral/persona=negative; faint praise and ambivalence: terse=neutral/rubric=neutral/persona=negative); the sarcasm item was unanimously negative. Final summary: 12 items x 3 raters: 9 unanimous, 3 routed to review. Output was identical across two runs (temperature=0), but labels can in principle vary with model updates.

---

### jury_votes.py

**Status:** PASS

**Description:** Three juror framings (terse, anti-length rubric, teaching-assistant persona) vote a/b/tie on 8 dpo_jury-shaped preference pairs, 6 constructed with a clearly better "a" (label skew is the point) and 2 close concise-vs-instructive pairs where the rubric and persona tie-break rules point opposite ways. self_check() asserts all metric implementations against hand-derived cases - including a missing-cell matrix (alpha 8/15, raw 7/9) and a below-chance Fleiss case (-0.2) - before any model call. The persona juror deterministically recuses on the fib pair (simulated self-preference recusal), leaving a missing cell: Krippendorff's alpha handles it natively, Fleiss' kappa is computed on the 7/8 complete rows only, as printed.

**Result:** self_check passed. Vote distribution {'a': 19, 'b': 4}, 83% 'a'. Raw agreement 1.000 on the 6 skewed pairs; on the 2 close pairs terse and persona voted b while rubric voted a, giving raw agreement 0.833 overall vs krippendorff alpha 0.421 and fleiss kappa 0.382 (7/8 complete rows) - the printed line cites 0.833 collapsing to 0.421 under 83% skew. Pairwise Cohen: terse_vs_persona 1.000, terse_vs_rubric 0.000, rubric_vs_persona 0.000 - the rubric juror voted 'a' on all 8 pairs, and a degenerate all-majority marginal yields kappa exactly 0 despite 75% raw agreement with terse. Final summary: 8 pairs x 3 jurors: 23 votes cast, 1 recused, 6 pairs unanimous among sitting jurors. Output was identical across two runs (temperature=0).

---
