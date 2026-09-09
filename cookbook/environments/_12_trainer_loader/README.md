# Trainer Loader

Read exported conversational SFT JSONL at the boundary where a trainer would
consume it. These examples validate and load message rows only; they do not
start a training job.

## Files

- `basic.py` — export passing attempts, then load their `messages` arrays.
- `validate_messages.py` — enforce the portable row shape and allowed roles
  before handing rows to any trainer-specific adapter.

## When to use

Use this after [`_11_export_provenance/`](../_11_export_provenance/) when you
need to connect the generated file to a separate training system. The loader
deliberately ignores the provenance sidecar; archive it for audits while the
trainer consumes the text JSONL.

For run-to-run verification before generating another dataset, continue to
[`_13_saved_baselines/`](../_13_saved_baselines/).

## Run

```bash
python cookbook/environments/_12_trainer_loader/basic.py
python cookbook/environments/_12_trainer_loader/validate_messages.py
```

Requires `OPENAI_API_KEY`. Every example uses `gpt-5.5` through
`OpenAIResponses`.
