# Router

Cookbook examples for `cookbook/90_models/ramp`.

[Ramp Router](https://router.com) puts one OpenAI Responses endpoint in front of several
providers. Set your API key first:

```bash
export RAMP_ROUTER_API_KEY=***
```

Run examples with:

```bash
.venvs/demo/bin/python cookbook/90_models/ramp/<example>.py
```

## Router specifics

- Model ids are account-scoped. `GET https://api.router.com/v1/models` lists the ones your key
  can reach, along with each one's context window, capabilities and price.
- `models=[...]` routes across candidates instead of picking one. Entries are the `catalog_id`
  values from that listing (`openai:gpt-5-nano`), optionally suffixed with a service tier.
  See `fallback.py`.
- `metadata={...}` is stored with the request and is how you attribute spend in the dashboard.
- `allow_flex_tier` only applies to a single `model`, so it cannot be combined with `models`.
- `background=True` is not supported: Router queues the generation but serves no endpoint to
  read it back.
- `provider_timeout` and `timeout_before_headers` control how long Router waits on an upstream
  provider before moving on to the next candidate.
- Reasoning efforts are per-model and wider than OpenAI's. Values outside
  `minimal`/`low`/`medium`/`high` go through `reasoning={"effort": ...}`.
- `temperature` and `top_p` are rejected by reasoning models, so leave them unset unless the
  model you picked accepts them.
