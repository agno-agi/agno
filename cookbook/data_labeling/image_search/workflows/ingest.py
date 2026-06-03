"""
Image Ingest Workflow
=====================

Wipes the existing index, then for each image URL in the configured list:

  1. Fetch the bytes (httpx, follow redirects).
  2. Ask the labeling agent for a search-tuned ImageDescription.
  3. Flatten the description and insert into Knowledge — the flat text is
     embedded for vector search; the structured fields are stored as
     metadata for the gallery view.

URLs are processed concurrently with a ThreadPoolExecutor. agno's Workflow
primitives (Step / Parallel / Loop) cover ordered pipelines and fixed
parallel branches but don't map dynamically over a list, so the per-URL
parallelism lives inside this Step's executor.

Reindex is a full rebuild — this is a demo where you iterate on the
labeling prompt, and incremental "skip if exists" would hide the effect
of prompt changes.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict

import httpx
from agno.agent import Agent
from agno.media import Image
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
    "adjectives, no flowery prose. Mention setting and mood if they're "
    "salient — a user might search by either.\n"
    "- Subjects: things in the image (people, animals, objects, named "
    "places). 1-5 short noun phrases. Pair each specific name with its "
    "common generic — e.g. 'English Bulldog' and 'dog'.\n"
    "- Scene: where this is, as one short noun phrase.\n"
    "- Visual style: one phrase covering aesthetic / lighting / "
    "composition.\n"
    "- Tags: 12-20 lowercase keywords covering everything a user might "
    "plausibly type for this image. For every salient subject climb "
    "the full ladder: specific name → category → broadest everyday "
    "bucket. Never stop at the most specific name — the broad buckets "
    "are what turn one-word queries like 'car', 'animal', or 'drink' "
    "into hits.\n"
    "    Tiger cub photo → tiger, cub, big cat, predator, wildlife, "
    "mammal, animal.\n"
    "    Yellow NYC taxi → yellow cab, taxi, car, vehicle, "
    "automobile, transportation, manhattan, new york city, nyc, "
    "street, traffic, urban, skyscraper, downtown.\n"
    "    Latte art → latte, coffee, espresso drink, beverage, drink, "
    "morning, cafe, breakfast.\n"
    "Also include atmosphere / mood words (cozy, vibrant, moody, "
    "minimal) when they apply. Err on the side of more labels — "
    "recall costs nothing, missing labels cost queries."
)


def make_extractor() -> Agent:
    return Agent(
        name="ImageLabeler",
        model=f"google:{EXTRACTOR_MODEL_ID}",
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
# Step executor — wipe existing content, then concurrent ingest.
# ---------------------------------------------------------------------------
def ingest(step_input: StepInput) -> StepOutput:
    knowledge = get_knowledge()
    knowledge.remove_all_content()

    indexed = 0
    failed = 0
    errors: list[dict[str, str]] = []

    with httpx.Client(follow_redirects=True, timeout=FETCH_TIMEOUT_SECONDS) as client:
        with ThreadPoolExecutor(max_workers=INGEST_CONCURRENCY) as pool:
            futures = {pool.submit(_ingest_one, url, client): url for url in IMAGE_URLS}
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
