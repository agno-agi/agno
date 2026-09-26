# TogetherLink

Cookbook examples for `cookbook/90_models/togetherlink`.

[TogetherLink](https://togetherlink.dev) is a hosted, OpenAI-compatible gateway in front of
Together AI models. It authenticates with a regular Together API key and adds an `auto` model
that routes each request to a fast or frontier model.

Set your Together API key first:

```bash
export TOGETHER_API_KEY=***
```

Run examples with:

```bash
.venvs/demo/bin/python cookbook/90_models/togetherlink/<example>.py
```

Use `auto` (the default) or any model id from the gateway catalog, for example
`moonshotai/Kimi-K3`, `zai-org/GLM-5.3`, `zai-org/GLM-5.3-Flash` or
`deepseek-ai/DeepSeek-V4.1-Flash`. If you have the TogetherLink CLI installed,
`togetherlink models` prints the current catalog and pricing.

If an agent has both `tools` and `output_schema`, also set a `parser_model`, for example
`parser_model=TogetherLink(id="deepseek-ai/DeepSeek-V4.1-Flash")`. Without one, most gateway
models answer straight in JSON and skip the tool call.

The gateway models are reasoning models, and reasoning tokens count against `max_tokens`.
A small `max_tokens` can use up the whole budget before the model writes an answer.

TogetherLink is in beta and the gateway currently stores request prompts and responses for
tracing. Do not send secrets or regulated data unless your organization has approved it.
