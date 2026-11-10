# Learnings

Agent learning and the `/learnings` REST API use the same persisted records.
This lesson serves an agent that automatically extracts a user profile and
user memory, proves those records are readable over HTTP, and then walks the
manual CRUD surface.

## Files

| File | What it teaches |
|---|---|
| `learnings_with_agentos.py` | Serve a learning-enabled agent and the database behind `/learnings`. |
| `rest_api_learnings.py` | Read agent-written learnings, then create, list, get, patch, and delete records. |

## Prerequisites

Set `OPENAI_API_KEY`. The agent and both automatic learning extractors use
OpenAI Responses `gpt-5.5`. SQLite persists the demo data in
`tmp/learnings.db`; the client removes its uniquely named demo users after
each run.

## Run

Start the server:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/11_learnings/learnings_with_agentos.py
```

In another terminal, run the REST walkthrough:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/11_learnings/rest_api_learnings.py
```

The first agent run shares a name, work context, and response preference. A
non-streaming run waits for automatic profile and memory extraction, so the
next `GET /learnings?user_id=...` reads both `user_profile` and `user_memory`
records back immediately.

## REST surface

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/learnings` | List and filter records in a `{data, meta}` envelope. |
| `POST` | `/learnings` | Create one record; identity-keyed duplicates return `409`. |
| `GET` | `/learnings/users` | List owning user IDs and their latest update timestamps. |
| `DELETE` | `/learnings/users/{user_id}` | Delete every learning owned by one user. |
| `GET` | `/learnings/{learning_id}` | Fetch one record. |
| `PATCH` | `/learnings/{learning_id}` | Replace `content` and/or `metadata`. |
| `DELETE` | `/learnings/{learning_id}` | Delete one record. |

`user_profile`, `user_memory`, `session_context`, and `entity_memory` use
deterministic IDs derived from identity fields. Include those fields when
creating a record; for a user profile, retain `user_id` inside replacement
`content` so the learning store can deserialize it. PATCH does not change
identity fields. Other types such as `decision_log` use generated IDs and can
have multiple records per user.
