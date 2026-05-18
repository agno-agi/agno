# Text Multilabel Classification

Assign any subset of N tags to a piece of text. Unlike single-label
classification, multiple tags can apply to the same input.

## Files

- `basic.py` — text → set of tags from a flat label space.
- `with_confidence.py` — adds per-tag confidence.
- `hierarchical.py` — parent/child tags from a taxonomy.

## When to use

- Restaurant reviews tagged by `[food, service, value, atmosphere, cleanliness]`.
- Customer support tickets tagged by `[bug, feature_request, billing, account]`.
- News articles tagged by topic taxonomies (`sports/football`, `tech/ai`).

If exactly one label applies, use
[`text_classification/`](../text_classification/) instead.

## Run

```bash
python cookbook/data_labeling/text_multilabel_classification/basic.py
python cookbook/data_labeling/text_multilabel_classification/with_confidence.py
python cookbook/data_labeling/text_multilabel_classification/hierarchical.py
```

Requires `OPENAI_API_KEY`.
