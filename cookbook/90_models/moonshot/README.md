# Moonshot

Cookbook examples for `cookbook/90_models/moonshot`.

Run examples with:

```bash
.venvs/demo/bin/python cookbook/90_models/moonshot/<example>.py
```

## Reasoning

Kimi models reason before answering and return their thinking as `reasoning_content`,
which Agno parses automatically and feeds back into the conversation on later turns.

Two parameters control that reasoning. Which one applies depends on the model
generation, and parameters that do not apply are ignored by the API:

| Parameter | Sent as | Used by |
|-----------|---------|---------|
| `reasoning_effort` | top-level request field | Kimi K3 |
| `use_thinking` | nested `thinking` object | Kimi K2.x |

### `reasoning_effort`

Controls how much the model thinks before answering. See
[Use thinking effort](https://platform.kimi.ai/docs/guide/use-thinking-effort).

```python
MoonShot(id="kimi-k3", reasoning_effort="low")
```

Kimi K3 accepts `"low"`, `"high"` and `"max"`.

**It defaults to `"max"` when the parameter is omitted.** That is a strong default:
K3 will happily spend a minute or more reasoning before answering a prompt that does not
need it. Lowering it to `"low"` cuts that dramatically — several times faster on simple
prompts, with correspondingly shallower thinking.

So pick deliberately rather than leaving it unset:

- Leave it unset (or `"max"`) for genuinely hard reasoning — proofs, planning, multi-step
  analysis.
- Set `"low"` for chat, summarization, formatting, tool-calling loops, and anything else
  where the answer is not the bottleneck.

### `use_thinking`

Toggles thinking on the Kimi K2.x line, which reasons by default. See
[Use the Kimi K2 thinking model](https://platform.kimi.ai/docs/guide/use-kimi-k2-thinking-model).

```python
MoonShot(id="kimi-k2.6", use_thinking=False)  # faster, no reasoning_content
```

Leave it as `None` (the default) to use whatever the model does on its own. Note that
thinking cannot be turned off on every model — Kimi K3 always reasons.

## Structured output

Kimi returns structured data two ways, both driven by `output_schema`:

| Mode | Sent as | How to use it |
|------|---------|---------------|
| Structured output | `response_format={"type": "json_schema"}` | Default — just set `output_schema` |
| JSON mode | `response_format={"type": "json_object"}` | Add `use_json_mode=True` |

Native structured output constrains the response to your schema, so prefer it:

```python
agent = Agent(model=MoonShot(id="kimi-k3"), output_schema=MovieScript)
```

JSON mode only guarantees the output is valid JSON, not that it matches the schema — it
infers the shape from your field descriptions. Use it as a fallback where the
`json_schema` path is not accepted:

```python
agent = Agent(model=MoonShot(id="kimi-k3"), output_schema=MovieScript, use_json_mode=True)
```

Either way, Kimi only emits JSON *objects* — never a top-level JSON array. Wrap lists in
a field on your model rather than asking for an array at the root. See
[Use JSON mode](https://platform.kimi.ai/docs/guide/use-json-mode-feature-of-kimi-api).

## Media

Kimi accepts each media type differently, and Agno adapts automatically — you just attach
`images`, `files`, or `videos` to the run:

| Media | How Kimi receives it | Upload needed? |
|-------|----------------------|----------------|
| Image | Inline base64 in the message content | No |
| File (PDF, docx, code, ...) | Uploaded with `purpose="file-extract"`, text extracted and injected | Yes |
| Video | Uploaded with `purpose="video"`, referenced as `ms://<file-id>` | Yes |

Images are sent inline, so there is no upload step. Files cannot be attached inline (Kimi
rejects the file content part), so each is uploaded, its text is extracted, and that text
is injected into the message. Videos are uploaded and referenced by a Moonshot storage
URL. After an upload the Moonshot file id is stored on the media object itself, so
`add_history_to_context` does not re-upload the same media on later turns. See
[Use the Kimi vision model](https://platform.kimi.ai/docs/guide/use-kimi-vision-model).

## Examples

| Example | What it shows |
|---------|---------------|
| `basic.py` | Sync and streaming responses |
| `tool_use.py` | Calling tools with web search |
| `reasoning_effort.py` | Setting `reasoning_effort` on Kimi K3 |
| `thinking_mode.py` | Toggling thinking with `use_thinking` |
| `structured_output.py` | Structured output and JSON mode |
| `file_input.py` | Attaching a file (upload + extract) |
