# Image Extraction

Image → typed Pydantic object. Same shape as text extraction with image
input: descriptive attributes, OCR'd fields, structured metadata.

## Files

- `basic.py` — image → typed scene attributes.
- `with_confidence.py` — adds per-field confidence.
- `ocr_fields.py` — extract text-heavy fields from an image (sign, receipt,
  product label).

## When to use

- Auto-cataloging product photos (color, style, type).
- Pre-filling form fields from a photo (receipt, business card).
- Generating searchable metadata for a media archive (see also
  [`image_extraction_to_vectordb/`](../image_extraction_to_vectordb/)).

If you only need a label, use
[`image_classification/`](../image_classification/). If you need pixel
regions, use [`image_bounding_boxes/`](../image_bounding_boxes/).

## Run

```bash
python cookbook/data_labeling/image_extraction/basic.py
python cookbook/data_labeling/image_extraction/with_confidence.py
python cookbook/data_labeling/image_extraction/ocr_fields.py
```

Requires `OPENAI_API_KEY`. Swap the URLs for your own images as needed.
