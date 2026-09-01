"""
Scale-Out - With Cost Tracking
==============================

Adds one thing to basic.py: token and dollar accounting. Every RunOutput
carries run.metrics (input_tokens, output_tokens, reasoning_tokens); this
file aggregates them across the fan-out and prints per-row averages, run
totals, the estimated cost of this run at list prices, and the projection
to 100k rows - the number that decides whether a labeling job is a shrug
or a budget line.

gemini-3.5-flash is a reasoning model: thinking tokens are reported
separately in metrics but billed at the output rate, so billable output
here is output_tokens + reasoning_tokens. Only the successful call per row
is counted - a row that needed retries billed more than it reports.
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
# Prices - Gemini API list prices for gemini-3.5-flash, interactive tier,
# as of 2026-07-18 (https://ai.google.dev/gemini-api/docs/pricing). The
# Batch API runs the same model at 50% of these rates for jobs that can
# wait for asynchronous completion.
# ---------------------------------------------------------------------------
INPUT_PRICE_PER_1M = 1.50
OUTPUT_PRICE_PER_1M = 9.00
BATCH_DISCOUNT = 0.5
PROJECTION_ROWS = 100_000


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
    metrics = run.metrics  # RunMetrics of the successful call, or None
    return {
        "id": row["id"],
        "text": row["text"],
        "label": content.label,
        "latency": latency,
        "input_tokens": metrics.input_tokens if metrics is not None else 0,
        "output_tokens": metrics.output_tokens if metrics is not None else 0,
        "reasoning_tokens": metrics.reasoning_tokens if metrics is not None else 0,
        "has_metrics": metrics is not None,
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
    pprint({"label_counts": dict(Counter(row["label"] for row in results))})

    n = len(results)
    with_metrics = sum(1 for row in results if row["has_metrics"])
    total_input = sum(row["input_tokens"] for row in results)
    total_output = sum(row["output_tokens"] for row in results)
    total_reasoning = sum(row["reasoning_tokens"] for row in results)
    print()
    print("token accounting:")
    pprint(
        {
            "rows_labeled": n,
            "rows_with_metrics": with_metrics,
            "input_tokens": {
                "total": total_input,
                "per_row": round(total_input / n, 1),
            },
            "output_tokens": {
                "total": total_output,
                "per_row": round(total_output / n, 1),
            },
            "reasoning_tokens": {
                "total": total_reasoning,
                "per_row": round(total_reasoning / n, 1),
            },
        }
    )

    # Thinking tokens are billed at the output rate.
    billable_output = total_output + total_reasoning
    run_cost = (
        total_input / 1_000_000 * INPUT_PRICE_PER_1M
        + billable_output / 1_000_000 * OUTPUT_PRICE_PER_1M
    )
    per_row_cost = run_cost / n
    projected = per_row_cost * PROJECTION_ROWS
    print()
    print(f"wall clock: {wall_clock:.1f}s for {n} rows at concurrency {CONCURRENCY}")
    print(
        f"estimated cost this run: ${run_cost:.4f} "
        f"(${per_row_cost * 1000:.3f} per 1000 rows, interactive list prices)"
    )
    print(
        f"projected {PROJECTION_ROWS:,} rows: ${projected:.2f} interactive, "
        f"${projected * BATCH_DISCOUNT:.2f} via the batch API"
    )


if __name__ == "__main__":
    asyncio.run(main())
