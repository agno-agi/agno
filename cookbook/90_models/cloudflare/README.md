# Cloudflare AI Gateway

Cloudflare AI Gateway exposes an [OpenAI-compatible unified API](https://developers.cloudflare.com/ai-gateway/usage/chat-completion/) so you can call many vendors through one endpoint by setting the model id to `vendor/model`.

This cookbook uses **Workers AI** by default: you only need a Cloudflare API token and account id (no OpenAI or other vendor keys). Other vendors (`openai/...`, `anthropic/...`, etc.) need **BYOK** keys configured in the Cloudflare dashboard.

## 1. Create and activate a virtual environment

See the repository [Development setup](https://github.com/agno-agi/agno/blob/main/CONTRIBUTING.md#development-setup).

### 2. Export credentials

```shell
export CLOUDFLARE_API_TOKEN=***
export CLOUDFLARE_ACCOUNT_ID=***
# optional, defaults to the auto-created "default" gateway:
# export CLOUDFLARE_AI_GATEWAY_ID=my-gateway
```

Create an API token in the Cloudflare dashboard with permissions to use AI Gateway for your account.

### Default model (Workers AI)

The Agno `Cloudflare` model class defaults to a Workers AI chat model so the basic example runs with Cloudflare credentials only. Confirm the exact model id in the [Workers AI model catalog](https://developers.cloudflare.com/workers-ai/models/) if the default id changes.

**Building a Workers AI `id` for Agno / AI Gateway**

1. In the catalog, open a **Text generation** model you want (for example [gemma-4-26b-a4b-it](https://developers.cloudflare.com/workers-ai/models/gemma-4-26b-a4b-it/)).
2. On that page, copy the model binding id from the UI (format like `@cf/google/gemma-4-26b-a4b-it`).
3. Paste it into Agno as-is: `Cloudflare(id="@cf/google/gemma-4-26b-a4b-it")` or `Agent(model="cloudflare:@cf/google/gemma-4-26b-a4b-it")`. Agno turns `@cf/...` into `workers-ai/@cf/...` for the AI Gateway. The full `workers-ai/@cf/...` form still works if you type it yourself.

Workers AI lists **Gemma** and other Google-hosted open weights; it does not expose arbitrary **Gemini** API names. For Gemini through the gateway, use a `google/...` model string from the [unified API docs](https://developers.cloudflare.com/ai-gateway/usage/chat-completion/) plus Google BYOK in the dashboard.

### Other vendors (BYOK)

Models like `openai/...` or `anthropic/...` are forwarded to that vendor. Add the **vendor’s API key** in the Cloudflare dashboard (AI Gateway / stored keys), otherwise upstream may return **401**.

### 3. Install libraries

```shell
uv pip install -U openai agno
```

### 4. Run the basic example

```shell
python cookbook/90_models/cloudflare/basic.py
```

### String model syntax

```python
# Paste the catalog binding (Agno adds the workers-ai/ prefix):
Agent(model="cloudflare:@cf/google/gemma-4-26b-a4b-it")
# Or use the full gateway form:
Agent(model="cloudflare:workers-ai/@cf/meta/llama-3.3-70b-instruct-fp8-fast")
```

### Switching models (same idea as OpenRouter)

| | OpenRouter | Cloudflare AI Gateway |
| --- | --- | --- |
| Pick one route | `OpenRouter(id="anthropic/claude-3.5-sonnet")` | `Cloudflare(id="@cf/google/gemma-4-26b-a4b-it")` (catalog paste) or `Cloudflare(id="workers-ai/@cf/...")` |
| String helper | `Agent(model="openrouter:...")` | `Agent(model="cloudflare:@cf/...")` (only the first `:` splits provider vs id) |
| Extra fallbacks in the HTTP body | `models=[...]` (OpenRouter-specific) | Not supported on the compat endpoint; use [Dynamic routes](https://developers.cloudflare.com/ai-gateway/features/dynamic-routing/) and `id="dynamic/<route>"` |

Run `python cookbook/90_models/cloudflare/switch_model.py` for concrete examples.

### “No such model” (400)

Workers AI binding ids must match the [catalog](https://developers.cloudflare.com/workers-ai/models/) exactly (for example `@cf/meta/llama-3.1-8b-instruct` or the full `workers-ai/@cf/...` form). Inventing paths such as `@cf/meta/google/gemini-...` will fail. For Google **Gemini** via the unified API, use a `google/...` gateway model id and BYOK, not a made-up Workers AI slug.
