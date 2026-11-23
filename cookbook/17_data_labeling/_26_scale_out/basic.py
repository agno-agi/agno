"""
Scale-Out - Basic
=================

Every folder in this cookbook labels a handful of rows in a synchronous
loop. That shape does not survive contact with a real dataset: at a few
seconds per row, 100k rows is days of wall clock. This file runs the same
sentiment task as _01_text_classification as an async fan-out instead: one
reused agent, one agent.arun call per row, and an asyncio.Semaphore holding
at most 8 requests in flight.

The speedup is measured, not claimed. Per-row latency is timed inside the
semaphore, so the sequential estimate (rows x mean latency) and the wall
clock printed at the end are two observations of the same run.
"""

import asyncio
import time
from collections import Counter
from typing import Literal

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


async def label_row(row: dict, progress: Counter) -> dict:
    # Latency is timed inside the semaphore: queue time waiting for a slot
    # does not count, because a sequential run would not pay it either.
    async with SEM:
        start = time.perf_counter()
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
        latency = time.perf_counter() - start
    progress["done"] += 1
    if progress["done"] % PROGRESS_EVERY == 0:
        print(f"labeled {progress['done']}/{len(ROWS)} rows")
    return {
        "id": row["id"],
        "text": row["text"],
        "label": content.label,
        "latency": latency,
    }


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
async def main() -> None:
    progress: Counter = Counter()
    wall_start = time.perf_counter()
    results = await asyncio.gather(*[label_row(row, progress) for row in ROWS])
    wall_clock = time.perf_counter() - wall_start

    print()
    print("example labeled rows:")
    pprint([{k: v for k, v in row.items() if k != "latency"} for row in results[:2]])

    print()
    pprint({"label_counts": dict(Counter(row["label"] for row in results))})

    latencies = [row["latency"] for row in results]
    mean_latency = sum(latencies) / len(latencies)
    sequential_estimate = mean_latency * len(results)
    print()
    print(f"labeled {len(results)} rows at concurrency {CONCURRENCY}")
    print(f"wall clock: {wall_clock:.1f}s")
    print(f"mean per-row latency: {mean_latency:.2f}s")
    print(
        f"sequential estimate: {len(results)} rows x {mean_latency:.2f}s "
        f"= {sequential_estimate:.1f}s"
    )
    print(f"measured speedup: {sequential_estimate / wall_clock:.1f}x")


if __name__ == "__main__":
    asyncio.run(main())
