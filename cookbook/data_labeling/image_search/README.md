# Image Search

A working searchable image library, end-to-end. An extraction agent
describes each image with search-tuned metadata, descriptions are embedded
and stored in a vector DB, and a browser UI lets you query the library in
natural language. One AgentOS process, one HTML file, four endpoints.

This is the productized version of
[`_09_image_extraction_to_vectordb`](../_09_image_extraction_to_vectordb/) —
that cookbook is the minimal pipeline; this one wraps it in a workflow,
endpoints, and a UI.

## What you get

| Endpoint                              | Source             | Purpose                       |
|---------------------------------------|--------------------|-------------------------------|
| `GET /ui`                             | explicit route     | Single-file HTML UI           |
| `GET /knowledge/content`              | AgentOS (native)   | Gallery list (paginated)      |
| `POST /knowledge/search`              | AgentOS (native)   | Vector search                 |
| `POST /workflows/image-ingest/runs`   | AgentOS (native)   | Reindex (background, polled)  |

All four routes come from a single `AgentOS(knowledge=..., workflows=..., base_app=...)`
call. The only custom Python is the labeling agent and the ingest loop.

## How it works

1. **Ingest** — the `image-ingest` workflow fetches each URL (httpx,
   redirects on), passes the bytes to a Gemini agent with
   `output_schema=ImageDescription`, and inserts the structured result into
   one shared `Knowledge` instance. The flattened description (caption +
   subjects + scene + style + tags) becomes the embedded text; the full
   `ImageDescription` plus the source URL becomes the metadata. URLs are
   processed concurrently with a `ThreadPoolExecutor`. The workflow is
   idempotent — items already present in `contents_db` are skipped.

2. **Gallery** — the UI hits `GET /knowledge/content`. Items render as
   cards with the image, caption, subjects, scene, visual style, and tag
   chips.

3. **Search** — the UI hits `POST /knowledge/search`. The query is
   embedded with `GeminiEmbedder`, matched against the stored description
   vectors, and the top hits come back with their full metadata for
   rendering.

4. **Reindex** — the UI's Reindex button hits the workflow endpoint with
   `background=true`, polls the run for status, and refreshes the gallery
   on completion. Top-right counter shows `N indexed`.

## Layout

```
cookbook/data_labeling/image_search/
├── README.md
├── TEST_LOG.md
├── requirements.in
├── requirements.txt
├── generate_requirements.sh
├── run.py                    AgentOS + UI route (entrypoint)
├── settings.py               URLs, paths, model IDs, concurrency
├── schemas.py                ImageDescription + flatten helper
├── db.py                     get_db(), get_knowledge() — shared singletons
├── workflows/
│   └── ingest.py             extractor agent + Step + Workflow
├── public/
│   └── index.html            single-file UI (Tailwind + Alpine + Lucide + PhotoSwipe — all CDN)
└── data/                     gitignored: chroma + sqlite live here
```

## Get started

### 1. Create a virtual environment

```bash
uv venv .venvs/image_search --python 3.12
source .venvs/image_search/bin/activate
```

### 2. Install dependencies

```bash
uv pip install -r cookbook/data_labeling/image_search/requirements.txt
```

### 3. Set your API key

```bash
export GOOGLE_API_KEY="..."
```

The demo uses `gemini-3.5-flash` for vision + structured output and
`gemini-embedding-001` for embeddings.

### 4. Serve

```bash
fastapi dev cookbook/data_labeling/image_search/run.py --port 7777
```

Then open <http://localhost:7777/ui>.

(Port 7777 because Docker Desktop's webview holds 8000, the fastapi-dev
default, which silently intercepts requests in confusing ways.)

The first time the page loads it will be empty. Click **Reindex** to fire
the ingest workflow against the 38 built-in Lorem Picsum URLs. With
`INGEST_CONCURRENCY=8` it takes ~15-20s against `gemini-3.5-flash`. When
it completes, gallery and search are populated.

## Tuning

In [`settings.py`](settings.py):

- `IMAGE_URLS` — swap the Picsum list for your own URLs (e.g. a list
  pulled from S3).
- `INGEST_CONCURRENCY` — raise for faster ingest on a higher quota.
- `EXTRACTOR_MODEL_ID` — bump to `gemini-3.5-pro` for higher-quality
  descriptions at slower / pricier ingest.
- `EMBEDDER_MODEL_ID` — swap to a different Gemini embedding model.

In [`schemas.py`](schemas.py):

- The `ImageDescription` fields determine what gets embedded and what the
  UI can render. Keep new fields short and search-flavored.

## Productionizing

This is demo-grade. For production:

- Auth on the AgentOS (`authorization=True` with a `JWTValidator`).
- Presigned URLs in place of public-read S3.
- CloudFront in front of the bucket for cold-load latency.
- Background worker pool for ingest at real scale; the in-process Workflow
  is fine up to maybe a few thousand items.
- Migrate ChromaDb to managed Chroma or pgvector once you outgrow local
  persistence.
