# Result Offloading

A long agentic run dies of its own tool output. One large search result sits
in the message list forever, re-sent on every later model call.

`Agent(offload_tool_results=True)` makes the transcript hold a pointer instead
of a payload. A result of 16,000 characters or more is written to the database
and the message gets an envelope:

```
<result id="res_a91c4f20b3" tool="fetch_catalog" lines="4000" size="142.9KB">
{first 20 lines / 1200 chars of the result}
</result>
Full result stored; read with read_result("res_a91c4f20b3") or search_result("res_a91c4f20b3", pattern).
```

The agent gets `read_result` and `search_result` to go back for the rest.
Nothing is summarized away, there is no model call on the write path, and
every read back is capped. Substitution happens before the tool message is
built, so the persisted session row carries the envelope too.

Pass a `ResultStore` to change the defaults:

```python
from agno.offload import ResultStore

Agent(offload_tool_results=ResultStore(threshold_chars=8000, ttl_seconds=86400))
```

`threshold_chars` defaults to 16,000, which is one `read_result` page. Below
that a stored result costs more to read back than it did inline.

**Never offloaded:** failed tool calls (the model needs the error text verbatim
to self-correct), results under the threshold, `read_result` /
`search_result`'s own output, a result that ends the run, and media. Only the
message text is replaced; images, videos, audio and files come through
untouched.

**Failure is loud, never silent.** If the write is refused or the backend
errors, the envelope says so and carries a head and tail preview instead of a
pointer, and the run continues.

**Requirements.** Offloading needs `SqliteDb` or `PostgresDb`; stored payloads
go through the sync filesystem backend. On any other database the setting is
honoured as off, with one warning naming the database.

Teams offload member answers the same way: see
[`../../03_teams/27_result_offloading/`](../../03_teams/27_result_offloading/).

| Example | What it shows |
|---|---|
| [`01_offload_tool_results.py`](./01_offload_tool_results.py) | A tool returns 143KB; the transcript holds under 1KB and the model still answers correctly. |
| [`02_result_store.py`](./02_result_store.py) | `ResultStore` used directly: offload, read a page, search, `live_ids()`, paging through a whole payload, cleanup. |

```bash
.venvs/demo/bin/python cookbook/02_agents/22_result_offloading/01_offload_tool_results.py
```
