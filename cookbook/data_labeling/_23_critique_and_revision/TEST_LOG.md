# Test Log - _23_critique_and_revision

Tested 2026-07-18 against `gemini-3.5-flash`, agno 2.7.4.

### basic.py

**Status:** PASS

**Description:** Draft -> critique -> revise against one written principle ("state uncertainty honestly; never present a guess as a fact"). Three module-level agents: a decisive drafter (default temperature, plain text), a temperature-0 critic with Critique(violates, critique) judging only against the principle, and a reviser that applies the critique. 5 prompts mixing guess-tempting questions (piano tuners, Mars landing year, RSA-2048) with settled facts. Writes SFT rows to data/generated/critique_sft.jsonl where response = revision if violates else draft, with full provenance.

**Result:** Summary line: "wrote 5 rows ... 4 revised, 1 passed through", identical counts across two runs today. The three guess-tempting prompts were flagged as expected (e.g. the draft asserted "the exact number of 82 piano tuners as a certain fact"; the revision hedged to "an estimated 70 to 100"). Surprise, reproduced in both runs: the boiling-point prompt was ALSO flagged - the temperature-0 critic ruled that "exactly 100 degrees Celsius" stated as absolute fact omits the standard-pressure assumption, a defensible strict reading of the principle. Only "Who wrote the novel 1984?" passed through untouched. Draft wording and violation counts can vary run to run with the drafter's sampling; the critic is the deterministic half.

---

### constitution_pairs.py

**Status:** PASS

**Description:** Same draft -> critique -> revise loop over 6 prompts, emitting preference pairs (chosen=revision, rejected=draft) only where the critic found a violation AND the revision differs from the draft. Writes pairs with principle + critique provenance to data/generated/constitution_pairs.jsonl, then prints a paste-ready Python list literal in dpo_jury.py's exact EXAMPLES shape (dict(id=..., source_family="google", gold=None, prompt=..., a=..., b=...); source_family names the drafting model's family so dpo_jury's self-preference recusal benches its Gemini juror on these pairs), alternating chosen between slots a and b by index parity.

**Result:** Summary line: "wrote 5 pairs ... from 6 prompts: 5 violations, 0 identical revisions dropped". Only the settled-fact control ("chemical symbol for gold") passed the critic; all 5 violating drafts produced genuinely different revisions (e.g. rejected "The Milky Way galaxy contains 100 billion stars." vs chosen "... estimated to contain between 100 billion and 400 billion stars."). The printed literal was extracted and eval'd in a fresh interpreter: valid Python, 5 dicts with exactly the keys id/source_family/gold/prompt/a/b, revision in slot a for even indices and slot b for odd, ready to drop into the _05 jury. Run three times with identical counts (5/5/0) - the last after source_family switched to the drafting model's family - though pair wording varies with drafter sampling.

---

### iterative_revisions.py

**Status:** PASS

**Description:** Adds a temperature-0 judge with Score(score 1-5, reason) grading against the principle plus general quality as a stopping rule: draft -> judge -> if score >= 4 stop, else critique + revise -> judge again, max 3 rounds. 4 prompts. Writes rows {"prompt", "final", "rounds", "score_trajectory"} to data/generated/iterative_revisions.jsonl.

**Result:** Summary line: "wrote 4 rows ...: 4 reached score >= 4, 0 hit the 3-round cap unconverged, 7 judge calls total". Trajectories: heartbeats [2, 5], fusion power [1, 5], why-is-the-sky-blue [5] (converged at round 1, no revision needed), grains of sand [1, 5]. Every guess-tempting draft scored 1-2, and a single critique + revision jumped each to 5 - with this strong a reviser, one round sufficed everywhere this run; the 3-round cap never bound. Trajectories vary run to run with drafter sampling; the judge's decisive low scores on unhedged guesses were consistent.

---
