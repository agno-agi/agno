# Test Log - _26_scale_out

Tested 2026-07-18 against `gemini-3.5-flash`, agno 2.7.4.

### basic.py

**Status:** PASS

**Description:** One reused temperature=0 agent labels 30 short product reviews (the _01_text_classification task shape) as an async fan-out: one agent.arun call per row under asyncio.Semaphore(8), a progress line every 10 rows, per-row latency timed inside the semaphore so the sequential estimate and the wall clock are two observations of the same run.

**Result:** Printed progress at 10/30, 20/30, 30/30. Label counts came back exactly as designed: {"positive": 10, "negative": 10, "neutral": 10}. Wall clock 7.3s, mean per-row latency 1.72s, sequential estimate 30 x 1.72s = 51.7s, measured speedup 7.0x at concurrency 8. Latency and speedup vary run to run; these are this run's observations.

---

### resumable.py

**Status:** PASS

**Description:** Adds checkpointed resume to the fan-out. Each finished row is appended and flushed to data/generated/labels.jsonl immediately, keyed by row id; on startup done ids are loaded and skipped. The demo deletes the checkpoint, runs pass 1 with only the first 15 rows (simulated interruption), then pass 2 with the full 30-row list. First version hit "Semaphore is bound to a different event loop" from two asyncio.run calls sharing a module-level semaphore; fixed by running both passes inside one asyncio.run(main()).

**Result:** Pass 1 printed "wrote 15 rows, skipped 0 already labeled, checkpoint now has 15". Pass 2 printed "wrote 15 rows, skipped 15 already labeled, checkpoint now has 30". Re-reading labels.jsonl confirmed 30 rows, 30 unique ids, keys id/text/label, and label counts {"positive": 10, "negative": 10, "neutral": 10}.

---

### with_cost_tracking.py

**Status:** PASS

**Description:** Adds token and dollar accounting to the fan-out. Aggregates input_tokens, output_tokens, and reasoning_tokens from run.metrics across all rows (fields verified against agno.metrics.RunMetrics and a live probe before writing), prices billable output as output + reasoning tokens at Gemini interactive list prices as of 2026-07-18 ($1.50/1M input, $9.00/1M output), and projects to 100k rows with the batch-API 50% tier alongside.

**Result:** metrics were present for 30/30 rows. Totals: 613 input tokens (20.4/row), 171 output tokens (5.7/row), 4459 reasoning tokens (148.6/row) - on this reasoning model the thinking tokens dominate the bill. Estimated cost this run $0.0426 ($1.420 per 1000 rows); projected 100,000 rows: $141.97 interactive, $70.98 via the batch API. Wall clock 7.5s for 30 rows at concurrency 8. Token counts and cost vary run to run; these are this run's observations.

---
