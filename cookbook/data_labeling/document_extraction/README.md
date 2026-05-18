# Document Extraction

Multipage PDF → typed Pydantic object. The closest neighbor in production
labeling: invoice fields, contract clauses, statement line items, lab
report fields.

## Files

- `basic.py` — extract top-level document metadata.
- `with_line_items.py` — extract a list of nested sub-objects (the
  line-item shape: invoice line items, recipe steps, contract clauses).
- `with_confidence.py` — adds per-field confidence.

These examples use a public recipe book PDF as the demo input so the
cookbook runs out of the box. For the production case, swap the URL or
provide a local `File(filepath="...")` to your own invoice / contract /
report PDF, and adapt the schema.

## When to use

- Lift invoice / receipt / statement fields into a database row.
- Extract contract clauses for review queues.
- Build a structured index over a PDF corpus.

If you only need a document-type label, use
[`document_classification/`](../document_classification/). For multi-agent
quality control on top of this primitive, see
[`quality_review/`](../quality_review/).

## Run

```bash
python cookbook/data_labeling/document_extraction/basic.py
python cookbook/data_labeling/document_extraction/with_line_items.py
python cookbook/data_labeling/document_extraction/with_confidence.py
```

Requires `OPENAI_API_KEY`.
