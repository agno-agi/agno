# Scale-Out

Every other folder in this cookbook labels a handful of rows in a synchronous
loop; this folder is what changes when the row count grows five zeros. The
labeling call itself stays exactly what
[`_01_text_classification/`](../_01_text_classification/) does - one reused
agent, a Pydantic schema, one label per row - and everything added here is
harness: an async fan-out with a bounded semaphore, a checkpoint that makes
interruption cheap, and token accounting that prices the job before you
commit to it.

## Files

- `basic.py` — async fan-out. One reused agent labels 30 short reviews via
  `agent.arun` under `asyncio.Semaphore(8)`, with a progress line every 10
  rows. Per-row latency is timed inside the semaphore, so the sequential
  estimate (rows x mean latency) and the wall clock printed at the end come
  from the same run - the speedup is a measured number (7.0x at concurrency
  8 in our test), not a claim.
- `resumable.py` — adds checkpointed resume. Each finished row is appended
  to `data/generated/labels.jsonl` the moment it lands, keyed by row id; on
  startup, done ids are loaded and skipped. The demo interrupts itself after
  15 rows, then reruns with the full list and prints skipped versus newly
  labeled. Kill a 100k-row job at row 60k and the rerun does 40k rows of
  work.
- `with_cost_tracking.py` — adds token and dollar accounting from
  `run.metrics`: per-row averages, run totals, the cost of the run at Gemini
  list prices, and the projection to 100k rows. On a reasoning model the
  thinking tokens dominate the bill: ~149 reasoning tokens per row versus
  ~6 output tokens in our run.

## Example rows

Rows written by `resumable.py` (the output file doubles as the checkpoint,
so `id` is the resume key):

```json
{"id": "r01", "text": "Absolutely love this blender, it crushes ice in seconds.", "label": "positive"}
{"id": "r15", "text": "Returned it immediately, the fan noise is unbearable.", "label": "negative"}
{"id": "r21", "text": "The box contains the charger, a cable, and a manual.", "label": "neutral"}
```

## When to use

- Running any folder's labeling task at real dataset size. The harness never
  looks inside the per-row call: swap in the schema and instructions from
  [`_03_text_extraction/`](../_03_text_extraction/),
  [`_15_document_classification/`](../_15_document_classification/),
  [`_17_llm_as_judge/`](../_17_llm_as_judge/), or any sibling folder and the
  fan-out, checkpoint, and accounting are unchanged.
- Jobs long enough to be interrupted - by a crash, a rate limit, or a
  laptop lid: `resumable.py`.
- Pricing a job before committing to it: `with_cost_tracking.py`. When the
  job is not latency-sensitive, provider batch APIs run the same model at
  roughly 50% of interactive list prices - at 100k rows that was the
  difference between $142 and $71 in our measured run.
- Filtering, deduplicating, and packaging what you labeled:
  [`_22_dataset_curation/`](../_22_dataset_curation/). Its judge gate is the
  same shape of per-row call, so it scales out with this exact harness too.

## Run

```bash
python cookbook/data_labeling/_26_scale_out/basic.py
python cookbook/data_labeling/_26_scale_out/resumable.py
python cookbook/data_labeling/_26_scale_out/with_cost_tracking.py
```

Requires `GOOGLE_API_KEY`.
