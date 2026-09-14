# Result Offloading

A long agentic run dies of its own tool output. One large search result sits
in the message list forever, re-sent on every later model call.

`Agent(offload_tool_results=True)` makes the transcript hold a pointer instead
of a payload. A result longer than 16,000 characters is written to the database
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

**Where it is stored.** The session row holds the envelope only. The full text
goes to AgentFS (`agno_fs`: the same SQLite file as the sessions, or the
schema `fs` on PostgreSQL, shared by every `db_schema`), and one index row per
result goes to `agno_tool_results` in your schema, with the payload's
namespace and path, its size, a preview and an optional expiry. `ResultStore`
sets the threshold, the preview, the lifetime, and with `fs=` any AgentFS
backend for payloads. Deleting a session removes its index rows and payloads.

Teams offload member answers the same way: see
[`../../03_teams/27_result_offloading/`](../../03_teams/27_result_offloading/).

| Example | What it shows |
|---|---|
| [`01_offload_tool_results.py`](./01_offload_tool_results.py) | A tool returns 143KB; the transcript holds under 1KB and the model still answers correctly. |
| [`02_result_store.py`](./02_result_store.py) | `ResultStore` used directly: offload, read a page, search, `live_ids()`, paging through a whole payload, cleanup. |
| [`03_where_results_live.py`](./03_where_results_live.py) | The three places a result lands: the envelope in the session row, the index row in `agno_tool_results`, the payload in AgentFS (`agno_fs`), counted with plain SQL. |
| [`04_custom_store_settings.py`](./04_custom_store_settings.py) | Threshold, preview size and a one-hour lifetime through `ResultStore(...)`; the bound copy on `agent.result_store`; the expiry sweep. |
| [`05_payloads_on_disk.py`](./05_payloads_on_disk.py) | `ResultStore(fs=...)` sends payloads to a local directory while the index stays on the db; the delete cascade removes the files. |
| [`06_postgres_layout.py`](./06_postgres_layout.py) | PostgreSQL: the index in your `db_schema`, the payload table in the shared `fs` schema, queried side by side. Needs `./cookbook/scripts/run_pgvector.sh`. |
| [`07_delete_session_cascade.py`](./07_delete_session_cascade.py) | Two users, two sessions: a delete as the wrong user removes nothing, the right user's delete takes session, index row and payload together. |

```bash
.venvs/demo/bin/python cookbook/02_agents/22_result_offloading/01_offload_tool_results.py
```
