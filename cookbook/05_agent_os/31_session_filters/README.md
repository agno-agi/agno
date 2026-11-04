# 31_session_filters

Search AgentOS sessions with nested AND/OR/NOT filters, sorting, and pagination.

AgentOS exposes two endpoints for this:

| Endpoint | Purpose |
|---|---|
| `GET /sessions/filter-schema` | Fields, operators, and logical operators the editor can offer |
| `POST /sessions/search` | One page of sessions matching a filter, plus the total match count |

Filterable fields:

| Field | Type | Operators |
|---|---|---|
| `session_id`, `session_name`, `user_id`, `agent_id`, `team_id`, `workflow_id` | string | `EQ`, `NEQ`, `IN`, `CONTAINS`, `STARTSWITH` |
| `session_type` | `agent` / `team` / `workflow` | `EQ`, `NEQ`, `IN` |
| `created_at`, `updated_at` | ISO datetime or epoch seconds | `EQ`, `NEQ`, `GT`, `GTE`, `LT`, `LTE` |

`CONTAINS` and `STARTSWITH` are case-insensitive. A session without a value for a field
never matches a condition on that field, including under `NOT`.

`session_name` (labelled "Saved Session Name") matches only a name that was set or saved for the
session. A session without one is listed under a title taken from its first message, and name
filters do not match that title.

A request body looks like this (`limit` is at most 100):

```json
{
  "filter": {
    "op": "AND",
    "conditions": [
      {"op": "EQ", "key": "user_id", "value": "alice"},
      {"op": "CONTAINS", "key": "session_name", "value": "billing"}
    ]
  },
  "page": 1,
  "limit": 20,
  "sort_by": "created_at",
  "sort_order": "desc"
}
```

## Files

- `server.py` - An AgentOS on port 7779 with sample sessions for two agents, a team, and two users. No model calls are made.
- `search_sessions.py` - Searches with `AgentOSClient.asearch_sessions` and `search_sessions`: one agent for one user, a name substring, a date range, negation, and pagination.

## Run

```bash
.venvs/demo/bin/python cookbook/05_agent_os/31_session_filters/server.py
.venvs/demo/bin/python cookbook/05_agent_os/31_session_filters/search_sessions.py
```
