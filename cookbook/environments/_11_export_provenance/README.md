# Export Provenance

Keep verification evidence beside a portable SFT dataset. The JSONL contains
only conversational messages; scores, attempt indexes, and environment and
policy fingerprints live in a deterministic `.meta.json` sidecar.

## Files

- `basic.py` — export a learning-zone dataset and locate its sidecar.
- `inspect_sidecar.py` — read the sidecar and join each JSONL row back to its
  task, attempt, and score.

## When to use

Use this after [`_10_export_sft/`](../_10_export_sft/) when a dataset needs
recorded provenance. Keep the JSONL and sidecar together in a trusted artifact
store when moving them.
The next folder, [`_12_trainer_loader/`](../_12_trainer_loader/), shows the
separate consumer boundary: a trainer loader reads only the message rows.

The sidecar records where the exported rows came from, but it does not contain a
digest that authenticates the JSONL. Treat the pair as one trusted artifact; a
same-length replacement JSONL would not be detected by the sidecar alone. It also
does not claim that training happened or that the dataset will improve a model.

## Run

```bash
python cookbook/environments/_11_export_provenance/basic.py
python cookbook/environments/_11_export_provenance/inspect_sidecar.py
```

Requires `OPENAI_API_KEY`. Every example uses `gpt-5.5` through
`OpenAIResponses`.
