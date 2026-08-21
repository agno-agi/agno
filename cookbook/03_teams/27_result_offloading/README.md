# Result offloading

A team leader pays for every member answer twice: once when it arrives, and again on every turn after that, because history replays it. A leader with three members and ten delegations is carrying ten full reports it has already read.

`Team(offload_tool_results=True)` writes any result longer than 16,000 characters to a file and puts a short envelope in the message instead. That covers the leader's own tool results and every member answer.

```
<result id="res_a91c4f20b3" tool="delegate_task_to_member" lines="1503" size="142.9KB">
{first 20 lines / 1200 chars of the member's answer}
</result>
Full result stored; read with read_result("res_a91c4f20b3") or search_result("res_a91c4f20b3", pattern).
```

Pass a `ResultStore` instead of `True` to set the threshold, the preview size, the lifetime, or where payloads live. The default threshold is one `read_result` page (16,000 characters); below that a stored result costs more to read back than it did inline.

```python
from agno.offload import ResultStore

Team(offload_tool_results=ResultStore(threshold_chars=8000, ttl_seconds=3600))
```

A member's answer arrives as the result of the delegation tool, so this is what it covers. The leader and every member get `read_result` and `search_result`, and a system-message line that explains the envelope; nothing needs to be added to their instructions. Nothing is summarized away, there is no model call on the write path, and every read back is capped.

Over six delegations of a 224,000 character answer, the largest prompt the leader is handed goes from 1,120,927 characters to 8,807. `test_six_delegations_stay_flat_with_offloading` measures it.

## What gets covered

A member's answer lands in more than one place. Offloading covers the two that a model reads:

| Where | Covered |
|---|---|
| The leader's transcript, and its history on later turns | yes |
| The member's own stored run, which it replays as its own history | yes |
| `RunOutput.member_responses`, returned to your code | no, by design |

The rule is one line: **offloading changes what a model reads, never what a caller reads.** So `output.member_responses[0].content` is always the whole answer, and `print_response` and the AgentOS session view still show it.

A paused run is never offloaded. Resuming replays its messages verbatim, so a pointer there would lose the conversation that produced the pending tool call.

`ResultStore(member_responses=False)` keeps stored member runs verbatim if you want them for audit, and offloads only the leader's side.

One cost worth knowing. A member's answer is now stored twice as a payload: once for the leader's delegation result, once for the member's own run. For a 224,000 character answer that is 448KB of payload where the answer used to sit inline in the run row at about the same total. So covering the member's run buys context, not disk. Storing one payload per distinct answer would buy both, and needs a content hash on the index row.

## Members share the store

Members run on the leader's store, under the team's session id, so one result id works anywhere in the team. The leader can hand a report to the next member by naming its id in the task, and that member reads it back itself. `handing_a_result_to_a_member.py` shows that.

Members inherit the team's store; their own `offload_tool_results` setting is never modified. A member that sets its own `offload_tool_results=ResultStore(...)` keeps those settings, bound to the team's database, so its results stay reachable from the rest of the team. The binding is redone every time a team initializes, so a member moved to another team follows that team.

## What is never offloaded

- Failed tool calls. The model needs the error text verbatim to correct itself.
- Results under the threshold, and `read_result` / `search_result` output, which is already capped. Those two also do not count against `tool_call_limit`, so a leader that spent its budget delegating can still read what it was told to read.
- Any result that ends the run, which is what `Team(respond_directly=True)` produces. That result is the answer, so a pointer in its place would replace the answer with a reference to it.
- Media. Only the message text is replaced.

## Requirements

Offloading needs `SqliteDb` or `PostgresDb`. On any other database the setting is honoured as off, with one warning naming the database. It never pretends to have stored something it did not.

## Files

- `offload_member_results.py` - a leader with a platform builder, manager and engineer; prints the leader's transcript size after each turn and lists what is stored.
- `handing_a_result_to_a_member.py` - the leader passes a result id to the next member instead of the payload.
- `member_store_settings.py` - one member inherits the team store, one opts out with `offload_tool_results=False`, one keeps its own `ResultStore(...)` settings; prints each member's store and what its stored history holds.

## Prerequisites

- Load environment variables (for example, OPENAI_API_KEY) via direnv allow.
- Use .venvs/demo/bin/python to run cookbook examples.
- The agent-level examples live in [`../../02_agents/22_result_offloading/`](../../02_agents/22_result_offloading/).
