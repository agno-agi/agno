# Advanced session filters

Run the self-contained example without an API key or external database:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/28_session_filters/session_filters.py
```

The Sessions page uses `GET /sessions/filter-schema` for autocomplete and
`POST /sessions/search` for nested `AND`/`OR` filters. Database ID and table remain
query parameters; the body contains `filter`, optional `session_type`, `page`,
`limit`, `sort_by` (`created_at` or `updated_at`), and `sort_order`.

Example queries in the filter editor:

```text
user_id = 'alice' AND session_name contains 'billing'
(session_type = 'agent' OR session_type = 'team') AND created_at >= '2026-10-01T00:00:00Z'
agent_id in 'support,sales'
```

Searchable fields: stored session name, session ID, user ID, session type,
agent/team/workflow IDs, and created/updated timestamps. Date values accept ISO
8601 (normalized to UTC) or epoch seconds. Name filters target the stored name,
not a title inferred from a run input. The usual inferred display title remains
available in returned sessions.

PostgreSQL and SQLite apply predicates before counting and pagination, in both
sync and async adapters. Other adapters use a batched portable scan; cost grows
with the number of visible sessions. User isolation constrains the entire search,
including OR branches. The endpoint requires `sessions:read`.

Python clients expose `search_sessions(...)` and `await asearch_sessions(...)`.
Both accept `filter_expr`, database/table, type, sorting, and pagination options.
