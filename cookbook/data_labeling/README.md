# Data Labeling

End-to-end example of using Agno for data labeling at scale. This cookbook
extracts structured fields from invoice PDFs with a two-labeler
ensemble, a reviewer that diffs them, and an adjudicator that resolves any
disagreement. It demonstrates the building blocks you'd use for most
labeling workloads: multimodal input, typed output schemas, multi-agent
composition, bounded-concurrency fan-out, and warehouse-shaped persistence.

## What this demonstrates

| Concern | How it shows up |
|---|---|
| Multimodal input | PDFs via `agno.media.File` attached to the workflow |
| Structured output | Pydantic `Invoice`, `LabelResult`, `DisagreementReport`, `FinalLabel` schemas with per-field confidence |
| Multi-agent composition | `Workflow(Parallel(Labeler A, Labeler B) -> Reviewer -> Condition(needs_adjudication, [Adjudicator]))` |
| Model diversity | Labeler A is OpenAI, Labeler B is Anthropic — disagreement signals where the two providers see the document differently |
| Bounded concurrency | `asyncio.Semaphore` in the batch driver |
| Retry + backoff | Per-model `retries=3, exponential_backoff=True` |
| Persistence | One workflow session per invoice in SQLite; full run history retained |
| Metadata for warehousing | `source_path, source_hash, labeler_a_model, labeler_b_model, schema_version, pipeline_version` attached to every run |
| Idempotency | `session_id = "invoice-<sha256[:16]>"`; re-running the batch updates the existing row instead of duplicating |
| Export | `export.py` flattens SQLite JSONB to one JSONL row per invoice |

## File layout

```
cookbook/data_labeling/
|-- README.md
|-- TEST_LOG.md
|-- requirements.in
|-- schemas.py          # Pydantic models that flow through the pipeline
|-- agents.py           # build_labeler_a, build_labeler_b, build_reviewer, build_adjudicator
|-- pipeline.py         # the Workflow itself (also runnable as a smoke test)
|-- run_batch.py        # batch driver: folder of PDFs -> SQLite, with Semaphore-bounded fan-out
|-- export.py           # SQLite -> flat JSONL for warehouse load
|-- data/invoices/      # drop sample PDFs here (gitignored, create on first run)
`-- tmp/                # SQLite + exported JSONL land here (gitignored)
```

## Run it

```bash
# From the agno repo root, with the demo venv active:
source .venvs/demo/bin/activate

# 1. Make the input + output folders (both are gitignored):
mkdir -p cookbook/data_labeling/data/invoices cookbook/data_labeling/tmp

# 2. Drop a few invoice PDFs into cookbook/data_labeling/data/invoices/
#    (any PDF works for a smoke test; the schema just leaves missing fields null)

# 3. Smoke-test the pipeline against a single public PDF:
python cookbook/data_labeling/pipeline.py

# 4. Run the batch driver over the folder:
python cookbook/data_labeling/run_batch.py cookbook/data_labeling/data/invoices/

# 5. Flatten the results for downstream load:
python cookbook/data_labeling/export.py
```

You need `OPENAI_API_KEY` and `ANTHROPIC_API_KEY` exported. To run with one
provider only, edit `agents.py` to point both `build_labeler_a` and
`build_labeler_b` at the same model with different temperature or
system prompt — the rest of the pipeline keeps working.

## Reading the output

Each invoice produces one row in the `labeling_sessions` table. The `runs`
column is JSONB with the full workflow trace. `export.py` flattens that into:

```json
{
  "session_id": "invoice-3f9c8b2e7a1d4e5f",
  "source_path": "/abs/path/invoice.pdf",
  "source_hash": "3f9c8b2e...",
  "labeler_a_model": "gpt-5.4",
  "labeler_b_model": "claude-sonnet-4-5",
  "schema_version": "1.0.0",
  "pipeline_version": "1.0.0",
  "final_invoice": { "vendor_name": "...", "total": 1234.56, "line_items": [...] },
  "labeler_a_invoice": { ... },
  "labeler_b_invoice": { ... },
  "disagreement_count": 2,
  "adjudicated": true,
  "created_at": 1715683200
}
```

That row is warehouse-shaped: drop it in Snowflake / BigQuery / Redshift
and query disagreement rates by vendor, model agreement over time, etc.

## Swapping pieces

- **Different schema**: edit `schemas.Invoice`. The labelers, reviewer, and
  adjudicator all use the same `LabelResult.invoice` field, so they pick
  up the new fields automatically.
- **Different models**: edit `agents.py`. Adding a third labeler is one
  more `Step` inside the `Parallel`.
- **Different storage**: swap `SqliteDb(...)` for `PostgresDb(...)` in
  `pipeline.build_pipeline`. The `metadata` column becomes a real JSONB
  column you can index.
- **Human-in-the-loop review**: attach `human_review=HumanReview(...)` to
  the reviewer step (see `cookbook/04_workflows/08_human_in_the_loop/`).

## Production checklist

This cookbook is honest about what it doesn't solve for a million-document
job. For production you'll add:

- **Rate limiting** — Agno does not throttle outbound model calls.
  Wrap `agent.arun` with `aiolimiter.AsyncLimiter(rpm, 60)` per provider,
  or run behind an upstream gateway (Helicone, Portkey, LiteLLM proxy).
- **Dead-letter queue** — `run_batch.py` records errors per item but
  doesn't retry the batch. Wire failed `session_id`s into a follow-up
  pass with a stricter / different model.
- **Idempotency on retry** — the `session_id = "invoice-<sha256>"` key
  makes re-running safe (upsert), but there's no built-in "skip if
  already labeled and adjudicated" check. Add a pre-flight SQL query if
  re-runs are expensive.
- **Provider Batch APIs** — for non-urgent labeling, OpenAI's and
  Anthropic's batch endpoints give a 50% discount with a 24-hour SLA.
  Agno does not expose these today; call the SDK directly and persist
  results with the same schema.
- **Prompt versioning** — Agno does not track prompt versions on the
  run record. The cookbook tracks `schema_version` and
  `pipeline_version` in `metadata` for the same reason. Bump them when
  instructions change so you can join against historical labels.
- **Authoritative cost tracking** — `RunMetrics.cost` is populated only
  when the provider returns it. If you need authoritative cost,
  attach a per-token rate table downstream of `export.py`.

## Related cookbooks

- `cookbook/09_evals/agent_as_judge/` — the closest existing labeling
  primitive shipped today. The cookbook here is what you reach for when
  the judge is the whole product, not just an eval.
- `cookbook/04_workflows/04_parallel_execution/parallel_basic.py` — the
  base shape this pipeline extends.
- `cookbook/04_workflows/08_human_in_the_loop/output_review/` — drop-in
  reviewer-with-retry machinery if you want humans on the reviewer step.
