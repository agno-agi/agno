# Verified Dataset

Turn passing attempts from difficult, tool-free tasks into conversational SFT
JSONL. The environment supplies repeated evidence; learning-zone selection
avoids overweighting already saturated rows.

## Files

- `basic.py` — verify, select the learning zone, and export passing attempts.
- `curate_learning_zone.py` — make the strict partial-rate curation rule explicit.
- `export_manifest.py` — pair the dataset and provenance sidecar with a compact manifest.

## When to use

Use this after a task set produces real disagreement and the passing assistant
responses are suitable supervision. `learning_zone()` selects task rows;
passing-only export filters the attempts within those rows.

Tool traces from [`_26_multi_step_tools/`](../_26_multi_step_tools/) are
excluded because the portable exporter is text-only. The resulting dataset can
be checked in [`_28_ci_gating/`](../_28_ci_gating/) or handed to a trainer
separately.

## Run

```bash
python cookbook/environments/_27_verified_dataset/basic.py
python cookbook/environments/_27_verified_dataset/curate_learning_zone.py
python cookbook/environments/_27_verified_dataset/export_manifest.py
```

Requires `OPENAI_API_KEY`. Export creates a dataset and provenance artifacts;
it does not train or update the running agent.
