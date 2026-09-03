# Test Log - _24_persona_driven_generation

Tested 2026-07-18 against `gemini-3.5-flash`, agno 2.7.4.

### basic.py

**Status:** PASS

**Description:** Persona agent generates 6 typed personas (occupation, expertise_level, communication_style, current_concern) in one call; prompt agent (created once at module level) writes 2 personal-finance questions per persona, one call per persona. Rows written to data/generated/persona_prompts.jsonl with the full persona as provenance.

**Result:** Summary line: "wrote 12 rows to .../persona_prompts.jsonl (6 personas x 2 prompts each)". The persona call satisfied both instruction constraints unprompted-checked-by-eye: 6 distinct occupations (freelance graphic designer, physics teacher, M&A attorney, commercial truck driver, pediatric resident, boutique hotel owner) spanning all three expertise levels (2 novice, 2 intermediate, 2 expert). Voice tracks persona clearly: the attorney cites IRC Section 408(d)(6) and AMT crossover points; the truck driver asks for "a straight answer" without jargon. Persona wording varies run to run; the 6 x 2 = 12 row count is an upper bound capped by slicing (fewer model returns would yield fewer rows).

---

### math_problems.py

**Status:** PASS

**Description:** 6 hand-written module-level personas condition one unit-rate multiplication word problem each. The problem shape is pinned by prompt (exactly two whole numbers 2-99 in digits, no other digits, answer = product, answer not in text) so a pure-Python verifier re-extracts the numbers with a regex and re-derives the gold; rows failing the count or product check are dropped with a printed reason. Rows {"problem", "answer", "persona_occupation"} written to data/generated/math_problems.jsonl.

**Result:** Summary line: "wrote 6 rows to .../math_problems.jsonl, kept 6, dropped 0 of 6 generated (product re-derived in code for every kept answer)". Ran three times today (the last after the verifier gained an explicit 2-99 range check); every run kept 6/6 - the model followed the exactly-two-numbers product shape every time, e.g. 6 dollars/cow x 75 cows = 450 (stated 450) and 12 shelves x 35 books = 420 (stated 420). All six final-run problems were additionally hand-solved to confirm the question semantics really ask for the product - the one failure mode the code check cannot see, as noted in the verify() comment. The drop path did not fire in any run; it exists for extra-digit, out-of-range, or wrong-product returns. Problems are recognizably persona-grounded (grain costs, glove boxes, taco prep, editing hours, fuel gallons, shelving).

---

### diversity_report.py

**Status:** PASS

**Description:** Generates 8 prompts about personal finance twice - unconditioned (one agent, one call) and conditioned on 8 hand-written personas (one call per persona, 1 prompt each) - then computes distinct-1, distinct-2, and mean pairwise Jaccard distance in pure stdlib, prints the side-by-side table plus mean tokens per prompt as length context, and prints a verdict citing the numbers whichever way they point. No JSONL; the printed report is the artifact.

**Result:** Final run verdict: "verdict: mixed - conditioning increased mean pairwise jaccard distance but not distinct-1, distinct-2 (distinct-1 0.642 -> 0.562, distinct-2 0.929 -> 0.921, mean pairwise jaccard distance 0.886 -> 0.908)"; mean tokens per prompt 18.5 unconditioned vs 59.4 conditioned. Ran 3 times today; the direction is run-dependent for distinct-2 (0.907-0.943 conditioned vs 0.907-0.929 unconditioned) and Jaccard distance (conditioned higher in 2 of 3 runs), while distinct-1 fell in ALL runs - a length confound, since conditioned prompts run ~3x longer and distinct-n penalizes repeated function words. Qualitatively the conditioned pool is clearly wider (milk-price volatility, TSP sequencing, remittances plus credit building, RSU/409A structuring vs the generic IRA/emergency-fund/credit-score set), but at N=8 lexical metrics only partially resolve this. One earlier run produced mild profanity from the "slangy and extremely online" crypto persona; a family-friendly instruction was added to the conditioned agent and the final runs are clean.

---
