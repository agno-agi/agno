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
| `GET` | `/learnings/users` | List the users that own learnings, with per-user counts |
| `GET` | `/learnings/{learning_id}` | Fetch a single record |
| `PATCH` | `/learnings/{learning_id}` | Update `content` and/or `metadata` (full replace) |
| `DELETE` | `/learnings/{learning_id}` | Delete a record |

## Auth and IDOR

When an authenticated request carries a JWT:

- **List**: results are scoped to the JWT subject AND records with no owner
  (`user_id IS NULL`) — this covers global, agent, team, session, and
  entity-scoped learnings. An explicit `user_id` query that doesn't match the
  JWT subject is rejected with `403`.
- **List users**: results are scoped to the JWT subject. An explicit `user_id`
  query that doesn't match the JWT subject is rejected with `403`.
- **Create**: the body's `user_id` must either be omitted/null (creates a
  global / non-user-scoped record) or match the JWT subject. A mismatch is
  rejected with `403`.
- **Single record GET / PATCH / DELETE**: records with `user_id IS NULL`
  remain accessible. Records owned by a different user return `404` (not
  `403`) to avoid leaking which IDs exist.

Without a JWT (legacy bearer-token mode) the request passes through.

## Identity field rules

- `user_id`, `agent_id`, `team_id`, `session_id`, `entity_id`, `entity_type`,
  `namespace`, and `learning_type` are immutable after creation. PATCH only
  modifies `content` and `metadata`.
- `workflow_id` is not exposed: workflows don't produce learnings directly —
  they go through their constituent agents/teams, which write `agent_id` or
  `team_id`.
