# Atlas Cloud Cookbook

Install the OpenAI-compatible client and configure your Atlas Cloud API key:

```shell
uv pip install 'agno[openai]'
export ATLASCLOUD_API_KEY="your-api-key"
```

Run one example at a time; each invocation submits a billable request:

```shell
python cookbook/90_models/atlascloud/basic.py
python cookbook/90_models/atlascloud/basic.py --async
python cookbook/90_models/atlascloud/basic.py --model-string
```

`AtlasCloud()` uses `deepseek-ai/deepseek-v3.2` by default. Pass `id=` to choose
another model from the [Atlas Cloud catalog](https://api.atlascloud.ai/api/v1/models).
Use the full catalog ID, including the organization prefix. Model features depend
on the selected model; this integration uses the Chat Completions API, not the
image or video generation endpoints.

The provider uses `https://api.atlascloud.ai/v1`. An explicit `api_key` takes
precedence over `ATLASCLOUD_API_KEY`; `OPENAI_API_KEY` is not used. SDK retries
are disabled by default because resubmitting a generation can incur another charge.
