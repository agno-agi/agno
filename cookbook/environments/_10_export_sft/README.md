# Export SFT

Turn verified text attempts into conversational SFT JSONL. The environment runs
each task repeatedly, the scorer marks correct attempts, and the exporter writes
the passing conversations from the learning zone.

## Files

- `basic.py` — run, select the learning zone, and export passing text attempts.
- `passed_only.py` — verify that failed attempts inside a learning-zone task are
  excluded from the training file.
- `empty_zone_guard.py` — remove stale output and guard the export when a
  selection has no useful rows.

## When to use

Use this after [`_06_learning_zone/`](../_06_learning_zone/) has shown which
tasks have a true middle-band pass rate. Exporting writes a dataset; it does not
train a model. The next folder,
[`_11_export_provenance/`](../_11_export_provenance/), inspects the sidecar that
keeps scores and fingerprints beside the portable JSONL.

Tool-bearing runs are not representable in this text-only format and are skipped.
See [`_17_tool_reliability/`](../_17_tool_reliability/) for tool verification.

## Run

```bash
python cookbook/environments/_10_export_sft/basic.py
python cookbook/environments/_10_export_sft/passed_only.py
python cookbook/environments/_10_export_sft/empty_zone_guard.py
```

Requires `OPENAI_API_KEY`. Every example uses `gpt-5.5` through
`OpenAIResponses`.
