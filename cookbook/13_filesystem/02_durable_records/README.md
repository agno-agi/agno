# Durable Records

Deduplicate work with a record log: the agent calls `check_lines` before it acts and `append_file` after. It keeps an exact, durable record of every item it has processed, so given a batch of items it works on only the genuinely new ones.

Neither of the other kinds of state can do this. User memory is LLM-curated, so it merges and rewrites what it stores, and a recurring job needs the record verbatim. Session state does not survive, and a scheduled agent gets a fresh session on every run.

The toolkit's built-in instructions already teach the check-before-act protocol and the `seen/` convention. The demo prompts below spell it out as well, so the runs stay deterministic. In your own agent the instructions alone usually carry it.

## Files

- `basic.py`: the minimal loop. Two passes over overlapping ticket batches, where the second pass acts only on the new ticket. Reach for this shape any time an agent must never repeat work.
- `radar_news_delta.py`: a scheduled news-brief agent, run twice. Run 1 briefs everything. Run 2 sees an expanded feed and briefs only what is new, with records partitioned into one `seen/` file per date.

## When to use

- Recurring jobs that must report only what is new: news digests, changelog watchers, inbox triage.
- Crawlers and monitors keeping a visited-set: URLs fetched, IDs processed, sources read.
- Any "have I already handled this exact item?" question, matched on exact lines rather than similarity. To checkpoint partial progress through one long task instead, see [`03_working_state/`](../03_working_state/). For getting started with FileSystem itself, see [`01_getting_started/`](../01_getting_started/).

## Run

```bash
python cookbook/13_filesystem/02_durable_records/basic.py
python cookbook/13_filesystem/02_durable_records/radar_news_delta.py
```

Requires `OPENAI_API_KEY`.

Both files use a fresh per-run SQLite file so repeated demo runs start clean. A real scheduled deployment pins one fixed, shared database. With a new store per process it would re-report everything, which is the bug this pattern exists to fix.
