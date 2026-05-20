# Text Extraction

Extract typed structured data from free-form text. The output is a Pydantic
object whose schema you control. The most common labeling shape in
production today.

## Files

- `basic.py` — text → flat typed object (single record).
- `with_confidence.py` — adds per-field confidence using a shared
  `ConfidentField` wrapper.
- `nested.py` — extract a list of nested sub-objects (action items, line
  items, attendees, etc.).

## When to use

- Pull contact info out of an email signature.
- Extract action items from a meeting transcript.
- Lift fields from unstructured user input into a database row.

If you only need a single label, use
[`_01_text_classification/`](../_01_text_classification/). If you need character
positions of mentioned entities, see
[`_04_text_span_labeling/`](../_04_text_span_labeling/).

## Run

```bash
python cookbook/data_labeling/_03_text_extraction/basic.py
python cookbook/data_labeling/_03_text_extraction/with_confidence.py
python cookbook/data_labeling/_03_text_extraction/nested.py
```

Requires `OPENAI_API_KEY`.
