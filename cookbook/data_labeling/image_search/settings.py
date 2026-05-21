"""
Settings for the image_search demo.

Centralized so the rest of the code can stay short. Holds the image set
(swap-in target for an S3 list later), Postgres URL, and ingest tunables.
"""

import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
PUBLIC_DIR = HERE / "public"

# Models. Same family as the rest of the data_labeling cookbooks.
EXTRACTOR_MODEL_ID = "gemini-3.5-flash"
EMBEDDER_MODEL_ID = "gemini-embedding-001"

# Postgres + pgvector. Matches the credentials baked into
# cookbook/scripts/run_pgvector.sh — override with DB_URL if you run your
# own instance.
DB_URL = os.getenv("DB_URL", "postgresql+psycopg://ai:ai@localhost:5532/ai")

# Vector + contents table names.
KNOWLEDGE_NAME = "image_library"
VECTOR_TABLE = "image_library_vectors"
KNOWLEDGE_TABLE = "image_library_contents"

# How many URLs to process concurrently inside the ingest workflow. Each
# in-flight URL holds an httpx fetch + a Gemini vision call + an embedding
# call. 8 is a comfortable middle for Gemini Flash without tripping the
# transient 5xx burst behavior we saw at higher concurrency.
INGEST_CONCURRENCY = 8

# HTTP fetch timeout when downloading image bytes (per URL).
FETCH_TIMEOUT_SECONDS = 30.0

# Image set — Lorem Picsum, stable IDs, served from a fast CDN.
PICSUM_IDS = [
    10,
    17,
    28,
    29,
    36,
    48,
    58,
    66,
    100,
    110,
    128,
    152,
    175,
    188,
    200,
    219,
    237,
    244,
    257,
    290,
    316,
    365,
    376,
    401,
    433,
    466,
    500,
    564,
    593,
    645,
    670,
    718,
    766,
    786,
    837,
    921,
    1015,
    1043,
]
IMAGE_URLS: list[str] = [
    f"https://picsum.photos/id/{picsum_id}/800/600" for picsum_id in PICSUM_IDS
]
