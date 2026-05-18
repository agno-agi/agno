# Image Classification

Assign a label to an image. Same shape as text classification - input is an
image, output is one or more labels from a closed set.

## Files

- `basic.py` — single label per image.
- `multilabel.py` — any subset of N tags per image.

## When to use

- Routing user-uploaded photos by content type.
- Pre-tagging a media library before manual cleanup.
- Quality / NSFW gates before ingest.

If you want to extract structured fields rather than labels (color, brand,
text on the image), use [`image_extraction/`](../image_extraction/).

## Run

```bash
python cookbook/data_labeling/image_classification/basic.py
python cookbook/data_labeling/image_classification/multilabel.py
```

Requires `OPENAI_API_KEY`. The samples use stable Wikimedia URLs - swap
your own image URLs or local paths in the `Image(...)` call.
