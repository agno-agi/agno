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
| `GET` | `/learnings/users` | List the users that own learnings, with last-activity timestamps |
| `DELETE` | `/learnings/users/{user_id}` | Delete a user's learnings (all types, or one via `?learning_type=`) |
| `GET` | `/learnings/{learning_id}` | Fetch a single record |
| `PATCH` | `/learnings/{learning_id}` | Update `content` and/or `metadata` (full replace) |
| `DELETE` | `/learnings/{learning_id}` | Delete a record |

## Auth and IDOR

Scoping follows the framework's opt-in `user_isolation` contract (via
`get_scoped_user_id`). It applies only to a **regular, non-admin** caller when
user isolation is enabled. **Admins** and requests running with isolation
disabled are unscoped and have full access — so, for example, an admin's
`GET /learnings/users` lists *all* users, not just themselves.

For a scoped (non-admin) caller:

- **List**: results are scoped to the caller AND records with no owner
  (`user_id IS NULL`) — this covers global, agent, team, session, and
  entity-scoped learnings. An explicit `user_id` query that doesn't match the
  caller is rejected with `403`.
- **List users**: results are scoped to the caller. An explicit `user_id`
  query that doesn't match the caller is rejected with `403`.
- **Delete user**: only the caller's own learnings may be deleted; a different
  `user_id` in the path is rejected with `403`.
- **Create**: the body's `user_id` must either be omitted/null (creates a
  global / non-user-scoped record) or match the caller. A mismatch is rejected
  with `403`.
- **Single record GET / PATCH / DELETE**: records with `user_id IS NULL`
  (shared agent/team/session/entity learnings) remain **readable** by any
  caller, but **mutating** them (PATCH/DELETE) is **admin-only** — a regular
  user gets `403`. Records owned by a different user return `404` (not `403`)
  to avoid leaking which IDs exist.

With isolation disabled, or for admins, or without a JWT, the request passes
through unscoped.

## Identity field rules

- `user_id`, `agent_id`, `team_id`, `session_id`, `entity_id`, `entity_type`,
  `namespace`, and `learning_type` are immutable after creation. PATCH only
  modifies `content` and `metadata`.
- `workflow_id` is not exposed: workflows don't produce learnings directly —
  they go through their constituent agents/teams, which write `agent_id` or
  `team_id`.

## Creating records (id derivation)

The learning stores key their records by a deterministic id derived from the
identity fields, not a random id. So `POST /learnings` derives the same id for
the identity-keyed types, ensuring a record created via the API reconciles with
what the agent reads and writes (no orphan, no duplicate):

| `learning_type` | derived id |
|---|---|
| `user_profile` | `user_profile_{user_id}` |
| `user_memory` | `memories_{user_id}` |
| `session_context` | `session_context_{session_id}` |
| `entity_memory` | `entity_{namespace}_{entity_type}_{entity_id}` |

- Provide the required identity field(s) for these types, or the request is
  rejected with `422`. If a record already exists for that identity, `POST`
  returns `409` — use `PATCH` to update it.
- Put the same identity fields inside `content` too (e.g. `user_id` for
  `user_profile`), so the agent's store can deserialize the record.
- Other types (e.g. `decision_log`) use a generated id, so a user can have many.
