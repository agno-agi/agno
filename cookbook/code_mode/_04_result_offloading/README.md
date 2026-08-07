# Result offloading

`Agent(offload_tool_results=True)` sets the threshold to 4000 characters; `offload_tool_results=12000` sets it explicitly. Results over the threshold are written to AgentFS and the message gets an envelope:

```
<result id="res_a91c4f20b3" tool="search_content" lines="8412" size="612KB">
{first 20 lines / 1200 chars of the result}
</result>
Full result stored; read with read_result("res_a91c4f20b3") or search_result("res_a91c4f20b3", pattern).
```

Substitution happens before the tool message is built, so the `ToolExecution` that persists into the session row carries the envelope too — session rows stay small for free.

**Never offloaded:** failed tool calls (the model needs the error text verbatim to self-correct), sub-threshold results, `read_result` / `search_result`'s own output, and media. Only `Message.content` is ever replaced; images, videos, audio and files come through untouched.

**Failure is loud, never silent.** If the write is refused (quota) or the backend errors, the envelope says so and carries a head **and** tail preview instead of a pointer, and the run continues.

- `basic.py` — an agent whose tool returns 143KB; the transcript holds under 1KB and the model still answers correctly.
- `with_ttl_and_store.py` — `ResultStore` used directly, without an agent: offload, read a bounded page, search, `live_ids()`, and cleanup.
