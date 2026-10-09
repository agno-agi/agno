# Arcmira: YouTube Transcript Search

[API documentation](https://arcmira.com/docs) · [OpenAPI specification](https://api.arcmira.com/v1/openapi.json)

Search indexed YouTube videos and livestreams for timestamped passages. Use the results to locate quotes and discussions across channels, with links back to their sources.

Set `ARCMIRA_API_KEY` to your Arcmira API key, then run the example from this checkout:

```sh
python cookbook/91_tools/arcmira/search.py
```

This calls the search API directly without an LLM. To use it with your existing Agno agent, add `ArcmiraTools(limit=5)` to the agent's `tools` list.

```python
from agno.tools.arcmira import ArcmiraTools

tools = ArcmiraTools(limit=5)
result = tools.search_transcripts(
    "open source AI",
    after="2026-09-01",
    before="2026-10-01",
    source="arcmira_premium",
)
print(result)
```

For an async application, call `await tools.asearch_transcripts("open source AI")`. Agno automatically selects this async implementation during async agent runs, under the same `search_transcripts` tool name.

The result limit is developer-controlled, from 1 to 20. Dates define a UTC window with an inclusive start and exclusive end. `channel_ids` accepts comma-separated YouTube channel IDs, not names.

Research requests use your account's search allowance. Plan restrictions, rate limits and usage errors propagate without automatic retries or a fallback to a different transcript source. This tool does not retrieve full Premium transcripts or create transcription jobs. See the [search reference](https://arcmira.com/docs/search) and [account tiers](https://arcmira.com/pricing) for access details.

Preserve `partial`, `failed_batches`, `search_index`, `access` and `note` fields when interpreting results. Empty results do not establish that a topic was never discussed. Use speaker names only when the response provides them. Resolve relative `watch_url` links against `https://arcmira.com` and cite the original timestamps.

API keys are configured on the toolkit, not passed by the model. Requests use HTTPS with a finite timeout and do not follow redirects.
