# Document Classification

Assign a document-type label to a (potentially multipage) PDF: invoice,
receipt, contract, spec sheet, report, recipe, etc.

## Files

- `basic.py` — single label per PDF.
- `with_confidence.py` — adds confidence in the label.

## When to use

- Routing inbound documents to the right downstream pipeline (an invoice
  goes to AP, a contract to legal review, a recipe to a content team).
- Coarse pre-filtering before a heavier extraction pipeline runs.

If you want fields rather than a label, use
[`document_extraction/`](../document_extraction/).

## Run

```bash
python cookbook/data_labeling/document_classification/basic.py
python cookbook/data_labeling/document_classification/with_confidence.py
```

Requires `OPENAI_API_KEY`. The samples use a public PDF hosted by
agno-public; swap the URL for your own PDF.
