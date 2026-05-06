# Learnings CRUD via AgentOS

These cookbooks demonstrate the `/learnings` REST endpoints exposed by AgentOS.
The endpoints provide CRUD operations over the `agno_learnings` table, which
backs every learning store (`user_profile`, `user_memory`, `entity_memory`, etc.).

## Files

| File | Purpose |
|------|---------|
| `learnings_with_agentos.py` | Starts an AgentOS with a learning-enabled agent. |
| `rest_api_learnings.py` | Hits the `/learnings` endpoints with `httpx`. |

## Running

In one terminal, start the AgentOS:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/learnings/learnings_with_agentos.py
```

In another, run the REST client:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/learnings/rest_api_learnings.py
```

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/learnings` | Paginated list with filters |
| `POST` | `/learnings` | Create a new learning record |
| `GET` | `/learnings/{learning_id}` | Fetch a single record |
| `PATCH` | `/learnings/{learning_id}` | Update `content` and/or `metadata` (full replace) |
| `DELETE` | `/learnings/{learning_id}` | Delete a record |

## Auth and IDOR

When an authenticated request carries a JWT, the `user_id` filter on list/create
is bound to the JWT subject (any client-supplied value is overridden), and
single-record fetches/updates/deletes return `404` if the record belongs to a
different user. Without a JWT, the request is unrestricted (legacy bearer-token
mode).

## Identity field rules

- `user_id`, `agent_id`, `team_id`, `session_id`, `entity_id`, `entity_type`,
  `namespace`, and `learning_type` are immutable after creation. PATCH only
  modifies `content` and `metadata`.
- `workflow_id` is not exposed: the framework does not currently produce
  workflow-scoped learnings.
