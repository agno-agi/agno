# Openai

OpenAI reasoning model examples, including effort, stream, and summary modes.

## Examples

- [`gpt_6.py`](gpt_6.py) — GPT-6 Astra with medium reasoning effort, reasoning summaries, and streaming.
- `o3_mini.py`
- `o3_mini_with_tools.py`
- `reasoning_effort.py`
- `reasoning_model_gpt_4_1.py`
- `reasoning_stream.py`
- `reasoning_summary.py`

## Run the GPT-6 example

Install `agno` and `openai`, then set `OPENAI_API_KEY` for an account with access to
`gpt-6-astra`:

```bash
python cookbook/10_reasoning/models/openai/gpt_6.py
```

See the [GPT-6 Astra model documentation](https://developers.openai.com/api/docs/models/gpt-6-astra)
and [reasoning guide](https://developers.openai.com/api/docs/guides/reasoning) for supported settings.
