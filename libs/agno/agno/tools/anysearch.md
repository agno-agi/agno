# AnySearch toolkit

Maintenance notes for `agno/tools/anysearch.py` (`AnySearchTools`) and `agno/context/web/anysearch.py` (`AnySearchBackend`).

Both files talk to AnySearch's REST API directly over `httpx` and share a wire contract, not code: the toolkit is sync + async and mounts on an agent, the backend is async-only and plugs into `WebContextProvider`. Keeping them independent keeps each readable on its own; a change to the wire contract usually belongs in both.

## Endpoints

| Operation | Request | Success envelope |
|-----------|---------|------------------|
| Search | `POST /v1/search` — `{query, max_results, tag?, params?, zone?, language?, format?}` | `{code: 0, data: {results: [{title, url, snippet?, content?}], metadata: {total_results, search_time_ms}}, request_id}` |
| Batch | 1-5 × `POST /v1/search` (client-side fan-out) | one search envelope per query |
| Extract | `POST /v1/extract` — `{url}` only; the endpoint rejects unknown fields | `{code: 0, data: {url, title, content}, request_id}` |
| Sub-domains | `GET /v1/sub-domains?domain=...` (1-5 domains) | `{code: 0, data: {domains: [...]}, request_id}` |

Batching is a client-side fan-out: the toolkit runs the queries concurrently (thread pool for the sync tools, `asyncio.gather` for the async ones) and reports per-query failures in place - including failures raised before the wire, such as params that cannot be serialized - so one bad query never fails the call. Both files clamp `max_results` to 1-10 and reject a batch or a sub-domain call above five items before spending a request. Search `content` is capped at `content_length_limit` (2000 by default) and extracted pages at `extract_length_limit` (50000 by default) or the backend's `_MAX_EXTRACT_CHARS`, because a page runs far longer than a snippet.

## Auth and quota

Auth is optional. Without a key, requests go out anonymously and are metered against AnySearch's daily free quota per client IP; with one, they bill the paid quota. `ANYSEARCH_API_KEY` supplies the key (or the `api_key` argument), `ANYSEARCH_API_BASE_URL` overrides the base URL, and the `X-Anysearch-Client` / `User-Agent` headers identify the caller.

## Error policy

Every failure is returned to the model as `{"error": ..., "request_id": ...}` rather than raised, so a run keeps going and the agent can report or retry. Non-2xx statuses and `code != 0` bodies map to short messages by status (400 invalid request, 401 invalid key, 403 expired key, 415 unsupported content type, 422 unable to extract, 429 rate limit, 502 upstream unavailable), and the API's own `message` is passed through as `detail` when it has one. A 2xx body that is not the documented envelope is reported as `unexpected response envelope from AnySearch` instead of being read as an empty result set, and any exception raised before the wire is caught the same way. On the `fetch_many` path a 429 turns into `RateLimited` with the response's `Retry-After`.

**Quota responses are withheld, whatever status they arrive with.** AnySearch's quota response can embed auto-generated credentials in its body, so a 402 - or any message shaped like credentials (`password`, `api_key`, `username`, "automatically generated") - reaches neither the tool result nor the logs: callers get a fixed message plus the request id. Do not surface the raw message here.

## Extending

- New capability domain: add it to the `Domain` Literal in `agno/tools/anysearch.py` (that Literal is what reaches the model as the `get_sub_domains` enum) and to the same Literal in the backend file.
- New tool: add the sync method with its async twin and register the pair in `async_tools`; the sync surface must stay free of coroutines or the framework's sync-tool guard rejects it.
- New endpoint parameter: keep it a constructor argument (an application-level preference) unless it is per-call, which is what `tag` and `params` are for.

## Tests

`libs/agno/tests/unit/tools/test_anysearch.py` and `libs/agno/tests/unit/context/test_anysearch_backend.py` mock the transport with `httpx.MockTransport`, so they run offline:

```shell
pytest libs/agno/tests/unit/tools/test_anysearch.py libs/agno/tests/unit/context/test_anysearch_backend.py
```

They cover the request shape (URL, body, headers, absent optional fields), `max_results` clamping, result mapping and truncation, one case per status code, the redaction rule, envelope-shape drift, batch caps and per-query isolation (including failures raised before the wire), and sync/async parity. Live check, keyless or keyed:

```shell
python -c "from agno.tools.anysearch import AnySearchTools; print(AnySearchTools().search('latest CPython release', max_results=2))"
```
