# Inter-Annotator Agreement

Measure whether independent annotators reproduce each other's labels — the
standard reliability check for any labeling pipeline. Here the "annotators"
are instruction framings of one judge model at temperature 0, so every
disagreement traces back to the guideline wording, not sampling noise. The
metrics — raw agreement, Fleiss' kappa, Krippendorff's alpha (nominal), and
pairwise Cohen's kappa — are implemented in pure stdlib with the formulas
written as comments, and each file self-checks the implementations against
hand-derived values before making a single model call.

## Files

- `basic.py` — three framings of a sentiment guideline (terse, detailed
  rubric, annotator persona) label 12 texts, 4 of them designed to be
  ambiguous. Builds the item x rater matrix, computes all four metrics, and
  routes every non-unanimous item to a review list.
- `jury_votes.py` — the same metrics over dpo_jury-shaped preference votes.
  Three juror framings vote a/b/tie on 8 deliberately skewed pairs; one
  juror recuses on one pair, leaving a missing cell that Krippendorff's
  alpha handles natively and Fleiss' kappa cannot (computed on complete
  rows only). Shows raw agreement collapsing toward chance-corrected
  reality under label skew.

Example output rows from one run (labels can vary run to run):

```text
Gorgeous screen and superb speakers, but the ...    negative   neutral  negative
{'raw_agreement': 0.833, 'fleiss_kappa': 0.742, 'krippendorff_alpha': 0.749, ...}
under label skew (83% of votes are 'a'), raw agreement 0.833 collapses to alpha 0.421 once chance agreement on the majority label is removed
```

## When to use

Whenever more than one labeler — model, framing, or human — touches the same
items and you need to know how much of their agreement is signal:

- Auditing whether a guideline rewrite actually changed labels
- Deciding if a single-model labeler is reliable enough to run alone
- Vetting jury-vote filters: a high raw-agreement threshold can pass mostly
  chance agreement when the label distribution is skewed, and a juror that
  always votes the majority label can show high raw agreement with zero
  chance-corrected agreement

To generate the preference votes measured here, see
[`_05_text_pairwise_preference/`](../_05_text_pairwise_preference/) (the
`dpo_jury.py` pattern). To act on flagged disagreements with a
reviewer/adjudicator pipeline, see
[`_18_quality_review/`](../_18_quality_review/). For the single-judge
scoring these metrics stress-test, see
[`_17_llm_as_judge/`](../_17_llm_as_judge/).

## Run

```bash
python cookbook/data_labeling/_19_inter_annotator_agreement/basic.py
python cookbook/data_labeling/_19_inter_annotator_agreement/jury_votes.py
```

Requires `GOOGLE_API_KEY`.
