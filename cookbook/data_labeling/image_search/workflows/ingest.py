"""
Image Ingest Workflow
=====================

For each image URL not already in the index:

  1. Fetch the bytes (httpx, follow redirects).
  2. Ask the labeling agent for a search-tuned ImageDescription.
  3. Flatten the description and insert into Knowledge — the flat text is
     embedded for vector search; the structured fields are stored as
     metadata for the gallery view.

URLs are processed concurrently with a ThreadPoolExecutor. agno's Workflow
primitives (Step / Parallel / Loop) cover ordered pipelines and fixed
parallel branches but don't map dynamically over a list, so the per-URL
parallelism lives inside this Step's executor.

Re-running is safe: items already present in contents_db are skipped by URL.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict

import httpx
from agno.agent import Agent
from agno.knowledge.content import ContentStatus
from agno.media import Image
from agno.models.google import Gemini
from agno.workflow import Step, StepInput, StepOutput, Workflow
from db import get_db, get_knowledge
from schemas import ImageDescription, to_searchable_text
from settings import (
    EXTRACTOR_MODEL_ID,
    FETCH_TIMEOUT_SECONDS,
    IMAGE_URLS,
    INGEST_CONCURRENCY,
)

# ---------------------------------------------------------------------------
# Extraction agent — search-tuned instructions.
#
# We build a fresh Agent inside each worker rather than sharing one. Agent
# instances carry per-run state (session, history, structured-output
# parsing scratch) that isn't safe under concurrent .run() calls — sharing
# one would silently corrupt ~60% of outputs into raw strings.
# ---------------------------------------------------------------------------
EXTRACTOR_INSTRUCTIONS = (
    "You describe images for a natural-language image search index. "
    "Optimize every field for the queries users actually type:\n"
    "- Caption: read it back as a search query. Concrete nouns, common "
    "adjectives, no flowery prose.\n"
    "- Subjects: list the things in the image (people, animals, objects, "
    "named places). Short noun phrases, 1-5 entries.\n"
    "- Scene: where this is, as one short noun phrase.\n"
    "- Visual style: one phrase covering aesthetic / lighting / "
    "composition.\n"
    "- Tags: 5-10 lowercase keywords. Include synonyms and conceptual "
    "associations users might search by, not just literal contents.\n"
    "Be specific. Vague labels lose recall."
)


def make_extractor() -> Agent:
    return Agent(
        name="ImageLabeler",
        model=Gemini(id=EXTRACTOR_MODEL_ID),
        instructions=EXTRACTOR_INSTRUCTIONS,
        output_schema=ImageDescription,
    )


# ---------------------------------------------------------------------------
# Ingest one URL — fetch, describe, store. Pure function, safe to run from
# a thread pool. Returns nothing on success; raises on any failure so the
# pool can attribute it to the URL.
# ---------------------------------------------------------------------------
def _ingest_one(url: str, client: httpx.Client) -> None:
    response = client.get(url)
    response.raise_for_status()
    extractor = make_extractor()
    description = extractor.run(
        "Describe this image.",
        images=[Image(content=response.content)],
    ).content
    if not isinstance(description, ImageDescription):
        raise RuntimeError(
            f"agent returned {type(description).__name__}, not ImageDescription"
        )
    get_knowledge().insert(
        name=url,
        text_content=to_searchable_text(description),
        metadata={"url": url, **description.model_dump()},
    )


# ---------------------------------------------------------------------------
# Step executor — concurrent ingest with skip-if-already-indexed.
# ---------------------------------------------------------------------------
def ingest(step_input: StepInput) -> StepOutput:
    knowledge = get_knowledge()
    existing_contents, _ = knowledge.get_content(limit=10_000)
    existing = {
        c.name for c in existing_contents if c.status == ContentStatus.COMPLETED
    }

    to_process = [u for u in IMAGE_URLS if u not in existing]
    skipped = len(IMAGE_URLS) - len(to_process)
    indexed = 0
    failed = 0
    errors: list[dict[str, str]] = []

    with httpx.Client(follow_redirects=True, timeout=FETCH_TIMEOUT_SECONDS) as client:
        with ThreadPoolExecutor(max_workers=INGEST_CONCURRENCY) as pool:
            futures = {pool.submit(_ingest_one, url, client): url for url in to_process}
            for future in as_completed(futures):
                url = futures[future]
                try:
                    future.result()
                    indexed += 1
                except Exception as e:
                    errors.append({"url": url, "error": str(e)})
                    failed += 1

    summary: Dict[str, Any] = {
        "indexed": indexed,
        "skipped": skipped,
        "failed": failed,
        "total": len(IMAGE_URLS),
    }
    if errors:
        summary["errors"] = errors
    return StepOutput(content=summary)


# ---------------------------------------------------------------------------
# Workflow — wired in run.py.
# ---------------------------------------------------------------------------
ingest_workflow = Workflow(
    id="image-ingest",
    name="Image Ingest",
    description=(
        "Index images for natural-language search. For each image: download "
        "the bytes, describe it with search-tuned metadata, embed, and store. "
        "Idempotent — items already indexed are skipped."
    ),
    db=get_db(),  # required for background runs (the Reindex button)
    steps=[Step(name="Ingest", executor=ingest)],
)
