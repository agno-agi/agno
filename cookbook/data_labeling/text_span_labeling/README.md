# Text Span Labeling

Find labeled substrings within a text. The output is a list of `(text,
label)` pairs; character offsets are computed in post-processing using
`text.find()`. Asking the LLM to count characters is unreliable - the right
shape is to have the model return the literal substring and let Python
locate it.

## Files

- `basic.py` — entity span detection: PERSON, ORG, LOCATION, DATE.
- `pii_redaction.py` — PII span detection plus a simple redact step.

## When to use

- NER on customer support tickets to populate a contact graph.
- PII detection before storing user input.
- Highlighting claims or evidence in a longer document.

If you just want a typed object rather than spans, use
[`text_extraction/`](../text_extraction/).

## Run

```bash
python cookbook/data_labeling/text_span_labeling/basic.py
python cookbook/data_labeling/text_span_labeling/pii_redaction.py
```

Requires `OPENAI_API_KEY`.
