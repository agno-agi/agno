# Speko

Cookbook examples for `cookbook/90_models/speko`.

[Speko](https://speko.ai) is a voice router with an OpenAI-compatible chat
completions endpoint. `id="auto"` (the default) routes each request to the best
available LLM by live benchmarks; any routable `provider:model` ID can be pinned
instead, e.g. `Speko(id="openai:gpt-4.1-mini")`. Model catalog:
`GET https://api.speko.ai/v1/models`. Set your API key first:

```bash
export SPEKO_API_KEY=***
```

Run examples with:

```bash
.venvs/demo/bin/python cookbook/90_models/speko/<example>.py
```
