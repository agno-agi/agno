# Rejection Sampling

Generate K candidate outputs per prompt, verify or score each one, and keep
only the survivors. The filter is the product: what passes becomes training
data (verified reasoning traces, best-of-N picks), and the pass rates
themselves tell you which prompts are worth training on. This is the data
type behind cold-start reasoning recipes: sample from a teacher, check every
sample, keep what checks out.

This is not [`_17_llm_as_judge/`](../_17_llm_as_judge/). There, the judge
emits a score report and a human reads it. Here, the verifier or judge gates
a generation loop: its verdict decides row by row what enters the dataset.
`judge_gate.py` writes all N scores with each kept row and
`rl_prompt_selection.py` writes the pass rate; `basic.py` rows carry no
score - their provenance is the verified final answer itself.

## Files

- `basic.py` — verified reasoning traces. A teacher samples K=4 solutions
  per math/code problem; a pure-code verifier (integer equality against a
  hand-checked gold) keeps only traces whose final answer verifies. The
  reasoning text itself is not checked - a flawed derivation that lands on
  the right integer is kept. No judge anywhere in the keep path.
- `judge_gate.py` — best-of-N for prompts with no programmatic verifier. A
  generator samples N=3 candidates; a temperature-0 judge scores each
  against a rubric; the argmax candidate is kept only if it clears an
  absolute bar (score >= 4). All N scores are written with each row.
- `rl_prompt_selection.py` — pass rates as a prompt filter. Problems the
  model solves 4/4 teach nothing; problems it solves 0/4 give no reward
  signal. Keep the band in between (0 < pass@4 < 1) as RL training prompts.

## Example rows

Rows written by `basic.py` (every `final_answer` verified equal to the gold
before the row is kept):

```json
{"prompt": "How many ways can you choose 3 books from 7 distinct books?", "reasoning": "To find the number of ways to choose 3 books from 7 distinct books, we use the combination formula C(n, k) = n! / (k!(n-k)!). Applying this with n = 7 and k = 3 yields C(7, 3) = (7 * 6 * 5) / (3 * 2 * 1) = 35.", "final_answer": 35, "sample_index": 1}
{"prompt": "A train travels 180 km at 60 km/h, then another 120 km at 40 km/h. How many minutes does the whole trip take?", "reasoning": "The train's journey consists of two parts. First, it travels 180 km at 60 km/h, which takes 180 / 60 = 3 hours. Second, it travels 120 km at 40 km/h, which takes 120 / 40 = 3 hours. The total time for the trip is 3 hours + 3 hours = 6 hours. Since 1 hour is equal to 60 minutes, the whole trip takes 6 * 60 = 360 minutes.", "final_answer": 360, "sample_index": 2}
```

A row written by `judge_gate.py`, with all N scores as provenance:

```json
{"prompt": "Write a coherent paragraph of 30 to 40 words about winter mornings that does not contain the letter 'e' anywhere.", "chosen": "Cold air grips a frosty world. A soft light slips through our window. Frost clings to glass. Our sun glows with gold, warming a cold, still city. Fog drifts, but this bright dawn brings joy.", "chosen_score": 5, "all_scores": [5, 5, 5], "judge_reason": "The response is a coherent paragraph of exactly 35 words about winter mornings that completely avoids the letter 'e'."}
```

## Calibration notes from testing

Two observations from testing against `gemini-3.5-flash` (a reasoning
model), worth knowing before trusting either gate:

- The judge gate saturates when generator and judge are the same strength.
  In our runs every prompt scored [5, 5, 5] and nothing was dropped - and
  code-side checks confirmed the candidates really did satisfy the
  constraints (including a 35-word paragraph with no letter 'e' and a
  grammatical 10-word all-'x' sentence). The bar starts doing work when the
  generator is weaker than the judge, outputs get longer, or the rubric
  gets stricter. If you need sharper separation, use pairwise comparison
  ([`_05_text_pairwise_preference/`](../_05_text_pairwise_preference/))
  instead of absolute scores.
- Difficulty intuitions do not survive contact with a reasoning model.
  Problems designed as hard - a 60-step iterated map, the 613th prime, an
  exact 17-digit multiplication - all came back 4/4. The only prompt that
  landed in the learning zone was the one designed to be impossible: the
  12345th prime, which the model cannot sieve in its head but estimates,
  and it was exactly right 2 of 4 times. The band is also noisy at K=4:
  the 613th prime scored 2/4 in one run and 4/4 in the next. Measure pass
  rates rather than guessing them, and treat K=4 as a demo cap, not a
  measurement.

## When to use

- Distilling verified reasoning traces from a teacher model into SFT data:
  `basic.py` when answers are programmatically checkable, `judge_gate.py`
  when they are not.
- Selecting which prompts are worth RL compute: `rl_prompt_selection.py`.
- Scoring existing model outputs without gating a dataset:
  [`_17_llm_as_judge/`](../_17_llm_as_judge/).
- Deduplicating, filtering, and packaging rows that survived the gate:
  [`_22_dataset_curation/`](../_22_dataset_curation/).

## Run

```bash
python cookbook/data_labeling/_21_rejection_sampling/basic.py
python cookbook/data_labeling/_21_rejection_sampling/judge_gate.py
python cookbook/data_labeling/_21_rejection_sampling/rl_prompt_selection.py
```

`rl_prompt_selection.py` is the slow one - expect roughly 15 minutes,
dominated by reasoning tokens on the hard problems.

Requires `GOOGLE_API_KEY`.
