# Durable Records

The dedupe pattern: `check_lines` BEFORE acting, `append_file` after. An exact, durable, cross-session record of every item ever processed — input is a batch of items, output is work done on only the genuinely new ones.

This is what user memory cannot give you (LLM-curated memory merges and rewrites — probabilistic where a recurring job needs verbatim) and session state cannot either (scheduled agents get a fresh session per run).

The toolkit's built-in instructions already teach the check-before-act protocol and the `seen/` convention; the demo prompts below also spell it out so runs stay deterministic. In your own agent the instructions alone usually carry it.

## Files

- `basic.py` — the minimal loop: two passes over overlapping ticket batches; the second pass acts only on the new ticket. Reach for this shape any time an agent must never repeat work.
- `radar_news_delta.py` — the flagship: a scheduled news-brief agent run twice. Run 1 briefs everything; run 2 sees an expanded feed and briefs only the delta, with records partitioned into one `seen/` file per date.

## When to use

- Recurring jobs that must report only what is new: news digests, changelog watchers, inbox triage.
- Crawlers and monitors keeping a visited-set: URLs fetched, IDs processed, sources read.
- Any "have I already handled this exact item?" question — exact-line matching, not similarity. For checkpointing partial progress through one long task instead, see [`_03_working_state/`](../_03_working_state/). For getting started with FileSystem itself, see [`_01_getting_started/`](../_01_getting_started/).

## Run

```bash
python cookbook/filesystem/_02_durable_records/basic.py
python cookbook/filesystem/_02_durable_records/radar_news_delta.py
```

Requires `OPENAI_API_KEY`.

Both files use a fresh per-run SQLite file so repeated demo runs start clean. A real scheduled deployment pins one fixed, shared database instead — a new store per process re-reports everything, which is the bug this pattern exists to fix.
