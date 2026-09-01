"""
Scale-Out - Resumable
=====================

Adds one thing to basic.py: a checkpoint. Every labeled row is appended to
data/generated/labels.jsonl the moment it finishes, keyed by row id; on
startup the file is read back and already-labeled ids are skipped. Kill the
process at row 60k of 100k and the rerun does 40k rows of work, not 100k.

The demo proves the resume honestly: the first pass is handed only the
first 15 rows (a simulated interruption), the second pass is handed the
full list and prints how many rows it skipped versus newly labeled. The
checkpoint file is deleted at the start of the demo so reruns are
deterministic.
"""

import asyncio
import json
from collections import Counter
from pathlib import Path
from typing import Literal, TextIO

from agno.agent import Agent
from agno.models.google import Gemini
from pydantic import BaseModel, Field
from rich.pretty import pprint


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
class Classification(BaseModel):
    label: Literal["positive", "negative", "neutral"] = Field(
        ..., description="The assigned sentiment label"
    )


# ---------------------------------------------------------------------------
# Rows - 30 short product reviews, the _01_text_classification task shape
# ---------------------------------------------------------------------------
TEXTS = [
    "Absolutely love this blender, it crushes ice in seconds.",
    "Best headphones I have owned, the noise canceling is superb.",
    "Fast shipping and the fabric feels premium.",
    "Five stars, my kids have played with it every day for a month.",
    "Works perfectly with my setup, installation took two minutes.",
    "The battery lasts all week, exactly as advertised.",
    "Gorgeous color and the stitching is flawless.",
    "Customer support replaced my unit within a day, superb service.",
    "Crisp screen, snappy performance, worth every penny.",
    "This knife holds its edge better than ones triple the price.",
    "Broke after two uses, complete waste of money.",
    "The zipper jammed on day one and the seller ignores my emails.",
    "Smells like chemicals and the smell will not wash out.",
    "Half the screws were missing from the box.",
    "Returned it immediately, the fan noise is unbearable.",
    "The app crashes every time I try to pair the device.",
    "Arrived scratched and the corner of the case was cracked.",
    "Battery died completely after three weeks of light use.",
    "The sizing chart is wrong, it runs two sizes small.",
    "Overpriced junk, the hinge snapped within a week.",
    "The box contains the charger, a cable, and a manual.",
    "It works as described, nothing special.",
    "Delivered on Tuesday in a plain cardboard box.",
    "The manual says to charge it for six hours before first use.",
    "This model replaces the 2024 version of the same product.",
    "Available in three colors: black, white, and navy.",
    "It does what a kettle does, it boils water.",
    "The device weighs about 300 grams and fits in a coat pocket.",
    "Compatible with both USB-C and micro-USB cables.",
    "Median battery life in my tests was around six hours.",
]

ROWS = [{"id": f"r{i:02d}", "text": text} for i, text in enumerate(TEXTS, start=1)]

CONCURRENCY = 8
PROGRESS_EVERY = 10

CHECKPOINT_PATH = Path(__file__).parent / "data" / "generated" / "labels.jsonl"


# ---------------------------------------------------------------------------
# Create Agent - one agent, reused for every row
# ---------------------------------------------------------------------------
# The labeler runs at temperature=0 so a rerun assigns a row the same label.
# Labels can still drift with model updates and serving-side nondeterminism.
labeler = Agent(
    model=Gemini(id="gemini-3.5-flash", temperature=0),
    instructions="You classify product reviews by sentiment.",
    output_schema=Classification,
)

SEM = asyncio.Semaphore(CONCURRENCY)


# ---------------------------------------------------------------------------
# Checkpoint - the JSONL output file doubles as the resume state
# ---------------------------------------------------------------------------
def load_done_ids(path: Path) -> set:
    if not path.exists():
        return set()
    with path.open() as f:
        return {json.loads(line)["id"] for line in f if line.strip()}


async def label_row(row: dict, progress: Counter, checkpoint: TextIO) -> dict:
    async with SEM:
        content = None
        for attempt in range(3):  # retry schema breaks and transient API errors
            try:
                run = await labeler.arun(row["text"])
            except Exception:
                await asyncio.sleep(2**attempt)
                continue
            if isinstance(run.content, Classification):
                content = run.content
                break
        if content is None:
            raise RuntimeError(f"row {row['id']}: no valid label after 3 attempts")
    result = {"id": row["id"], "text": row["text"], "label": content.label}
    # Append and flush the moment the row finishes: everything written here
    # survives a crash, so a rerun redoes only the rows that never landed.
    checkpoint.write(json.dumps(result) + "\n")
    checkpoint.flush()
    progress["done"] += 1
    if progress["done"] % PROGRESS_EVERY == 0:
        print(f"labeled {progress['done']}/{progress['todo']} rows")
    return result


async def label_batch(rows: list) -> None:
    done = load_done_ids(CHECKPOINT_PATH)
    todo = [row for row in rows if row["id"] not in done]
    skipped = len(rows) - len(todo)
    progress: Counter = Counter(todo=len(todo))
    with CHECKPOINT_PATH.open("a") as checkpoint:
        results = await asyncio.gather(
            *[label_row(row, progress, checkpoint) for row in todo]
        )
    total = len(load_done_ids(CHECKPOINT_PATH))
    print(
        f"wrote {len(results)} rows, skipped {skipped} already labeled, "
        f"checkpoint now has {total}"
    )


# ---------------------------------------------------------------------------
# Run Agent - two passes prove the resume
# ---------------------------------------------------------------------------
async def main() -> None:
    print(f"pass 1: first 15 of {len(ROWS)} rows, then a simulated interruption")
    await label_batch(ROWS[:15])

    print()
    print("pass 2: rerun with the full list, resuming from the checkpoint")
    await label_batch(ROWS)


if __name__ == "__main__":
    CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
    CHECKPOINT_PATH.unlink(missing_ok=True)  # fresh demo, reruns deterministic
    asyncio.run(main())

    with CHECKPOINT_PATH.open() as f:
        checkpoint_rows = [json.loads(line) for line in f]
    print()
    print("example checkpoint rows:")
    pprint(checkpoint_rows[:2])
