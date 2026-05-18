# Image Extraction to Vector DB

End-to-end pipeline: extract structured descriptions from images with an
agent, then embed and store them in a vector database for similarity
search. The classic "build a searchable media library" labeling workflow.

## Files

- `basic.py` — extract → embed → store → search. All in one file.

No variants. The value here is the full pipeline.

## How it works

1. For each image URL, an agent extracts a structured `ImageDescription`
   (subject, setting, mood, key objects).
2. The structured fields are flattened to a single searchable string.
3. The string is embedded with `OpenAIEmbedder` and stored in LanceDb.
4. A text query searches the index and returns the most similar images.

## When to use

- Searching a stock photo library by natural-language query.
- Deduplicating a product catalog by visual + descriptive similarity.
- Building "find more like this" features on user-uploaded media.

## Run

Install the extra dependency for LanceDb first:

```bash
pip install lancedb tantivy
python cookbook/data_labeling/image_extraction_to_vectordb/basic.py
```

Requires `OPENAI_API_KEY`. Writes to `tmp/lancedb/` under the repo root.
