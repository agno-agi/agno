# Critique and Revision

Constitutional-AI-style supervised phase: draft -> critique against a
written principle -> revise. The constitution here is a single quality
principle ("state uncertainty honestly; never present a guess as a fact").
A decisive drafter answers, a temperature-0 critic judges the draft only
against the principle, and violating drafts are rewritten. Every row
carries full provenance (principle, critique, verdict), so downstream
curation can trace exactly why each response looks the way it does.

## Files

- `basic.py` - draft -> critique -> revise over 5 prompts: Fermi
  estimates and predictions that tempt overconfident guessing, plus
  settled facts that should pass untouched. Writes SFT rows where the
  response is the revision when the critic found a violation and the
  original draft otherwise.
- `constitution_pairs.py` - same loop over 6 prompts, but emits
  preference pairs (chosen=revision, rejected=draft) only where the
  critic found a violation and the revision actually differs from the
  draft. Ends by printing a paste-ready list literal in the exact
  EXAMPLES shape of `../_05_text_pairwise_preference/dpo_jury.py`: this
  folder generates the pairs that the `_05` jury consumes, so
  self-generated pairs get relabeled by a jury. The pairs carry
  `source_family="google"` (the drafting model's family), so dpo_jury's
  self-preference recusal benches its Gemini juror on them and only the
  other four families vote. Chosen/rejected alternate between slots `a`
  and `b` by index parity, so a jury with position bias is exposed.
- `iterative_revisions.py` - adds a temperature-0 judge (score 1-5
  against the principle plus general quality) as a stopping rule: revise
  only while the score is below 4, up to 3 judge rounds (so at most 2
  revisions). Rows store the score trajectory
  per prompt - the calibration signal for how many revision rounds a
  production pipeline should pay for.

Rows are written to `data/generated/` (gitignored - run the scripts to
regenerate). Abridged rows from a real run:

```json
{"prompt": "How many piano tuners work in Chicago?", "response": "There are an estimated 70 to 100 professional piano tuners currently working in Chicago. While the exact number fluctuates and is difficult to verify precisely, ...", "provenance": {"principle": "State uncertainty honestly. ...", "violates": true, "critique": "The draft presents the exact number of 82 piano tuners as a certain fact, failing to acknowledge that this is an estimated or variable quantity ...", "revised": true}}
{"prompt": "How many stars are in the Milky Way?", "chosen": "The Milky Way galaxy is estimated to contain between 100 billion and 400 billion stars, as the exact number cannot be directly counted.", "rejected": "The Milky Way galaxy contains 100 billion stars.", "provenance": {"principle": "State uncertainty honestly. ...", "critique": "The draft presents the estimated number of stars in the Milky Way as a definitive fact (\"100 billion stars\") instead of acknowledging it as an estimate ..."}}
{"prompt": "When will fusion power be commercially widespread?", "final": "It is highly uncertain when fusion power will become commercially widespread, with estimates ranging from 2050 to late in the 21st century. ...", "rounds": 2, "score_trajectory": [1, 5]}
```

## When to use

When you have a written quality or style principle and want the model to
enforce it on its own outputs:

- SFT distillation: `basic.py` rows train the principle into a model
  without the principle in the prompt at inference time
- Preference data: `constitution_pairs.py` pairs feed DPO or reward
  model training, with the critique as the documented reason
- Quality gating: `iterative_revisions.py` when one revision pass is not
  reliably enough and you need a measured stopping rule

The pairs this folder generates are consumed by the jury in
[`_05_text_pairwise_preference/`](../_05_text_pairwise_preference/) -
run `constitution_pairs.py`, paste the printed list into `dpo_jury.py`'s
EXAMPLES, and let independent judges relabel them. If you can verify
outputs mechanically instead of critiquing them, use
[`_21_rejection_sampling/`](../_21_rejection_sampling/). To filter or
dedupe the resulting corpus at scale, use
[`_22_dataset_curation/`](../_22_dataset_curation/).

## Run

```bash
python cookbook/data_labeling/_23_critique_and_revision/basic.py
python cookbook/data_labeling/_23_critique_and_revision/constitution_pairs.py
python cookbook/data_labeling/_23_critique_and_revision/iterative_revisions.py
```

Requires `GOOGLE_API_KEY`.
