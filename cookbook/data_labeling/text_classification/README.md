# Text Classification

Assign one of a fixed set of labels to a piece of text — the simplest data
labeling primitive. Input is a string; output is a label from a closed set.

## Files

- `basic.py` — text → single label.
- `with_confidence.py` — adds self-reported confidence per prediction. Use
  when you need to route low-confidence cases to a human or a stronger
  model.
- `with_rationale.py` — adds a short rationale string explaining why this
  label was chosen. Useful for auditability and as training data.

## When to use

When the output is one of a fixed, exhaustive set of labels:

- Sentiment: positive / negative / neutral
- Intent: refund / complaint / question / praise
- Topic: sports / politics / tech / health
- Quality bucket: good / mediocre / poor

If multiple labels can apply at once, use
[`text_multilabel_classification/`](../text_multilabel_classification/).
If the output is structured (entities, fields), use
[`text_extraction/`](../text_extraction/).

## Run

```bash
python cookbook/data_labeling/text_classification/basic.py
python cookbook/data_labeling/text_classification/with_confidence.py
python cookbook/data_labeling/text_classification/with_rationale.py
```

Requires `OPENAI_API_KEY`.
