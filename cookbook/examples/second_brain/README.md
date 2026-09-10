# Second Brain

Remember people, projects, and how you work across conversations. LearningMachine maintains a user profile, user memories, and an entity graph alongside explicit notes.

## Run locally

From the repository root:

```bash
cd cookbook/examples/second_brain
uv sync --locked
export OPENAI_API_KEY="your-openai-api-key"
uv run --no-sync demo.py
```

Each directory is a standalone uv project; a downloaded directory uses the same
commands after changing into it. `.env.example` is a template and is not loaded
automatically. Export variables explicitly. The lock pins published Agno 3.0.8;
Python 3.12 or newer is required. Model calls use `openai:gpt-5.6`.

## What to try

The demo uses actual LearningMachine tools to record Alex's preferred update style,
Harbor, and Jen as lead and reviewer. Each prompt has a fresh session. It asks for
recall, corrects the lead to Maya while retaining Jen as reviewer, then recalls
again. Expect Maya as current lead, Jen as reviewer, and concise updates.

```bash
uv run --no-sync demo.py --recall-only
```

This starts a new process using the saved learning stores. Inspect the printed
learning context and tool calls. No handwritten note substitutes for entity or
profile learning. Entity corrections use `remember_about` and model-assisted fact
supersession; if ambiguity remains, explicitly retire the stale fact with `forget`.

## Notes versus learning

| Store | Useful content | Scope |
| --- | --- | --- |
| FileSystem | Explicit documents, long reasoning, source wording | `brain/{user_id}` |
| User profile | Name and preferred name | `user_id` |
| User memory | Working preferences and useful observations | `user_id` |
| Entity memory | Current facts, dated events, relationships, pointers to notes | `namespace="user"` plus `user_id` |

All persist in `tmp/second_brain.db`. AGENTIC mode lets the agent decide when to
record learning through tools. Entity facts index the current state; notes preserve
detail. History is separate and cannot explain the fresh-session demonstration.
Do not store sensitive third-party information merely because it was mentioned.

FileSystem namespaces normalize case; learning user IDs are separate keys. Use
stable lowercase IDs consistently. This example has no pinned owner fallback.
It gives each user a private brain, including entities. A global entity namespace
would explicitly share entity knowledge across users.

## AgentOS and MCP

Export `JWT_VERIFICATION_KEY` as your trusted issuer's PEM RSA public key, then:

```bash
uv run --no-sync second_brain.py
```

AgentOS listens on `http://127.0.0.1:7777`; MCP is `/mcp` and REST docs are `/docs`.
Use a client that supplies `Authorization: Bearer <signed JWT>`. Configure the
issuer's JWT audience as `second-brain`, its `sub` as the stable user ID, and REST
scopes such as `agents:second-brain:run` and `sessions:read` as needed. Do not grant
admin scope to ordinary users. The only MCP tool is `ask_second_brain(message)`.
Custom MCP access is granted to verified callers; the tool requires a nonempty
subject and creates a fresh session each call. The authenticated JWT subject is
injected on the server; a model or client cannot choose the learning user ID.

The script refuses to serve without a key, and importing it without a key exposes
no ASGI app. Local `demo.py` calls use a trusted demo identity and need no JWT.
For remote exposure use HTTPS and a real trusted identity issuer; the example does
not provision either. SQLite is for local use; move to Postgres for production.
Notes and learned context used in runs are sent to the model provider.

## Extend it

Add a profile field or a custom learning store. The existing
[database-backed custom store](../../08_learning/08_custom_stores/02_custom_store_with_db.py)
implements the supported LearningStore protocol and registers through
`LearningMachine(custom_stores={...})`; no custom store is needed here.

## Validate

From this example directory:

```bash
uv run --no-sync pytest test_contracts.py -q
```

See [TEST_LOG.md](TEST_LOG.md) for measured results and limitations. To check the
checkout instead of the published package, prefix the command with
`PYTHONPATH=../../../libs/agno` while running from this directory. The source
revision is recorded in the collection's [validation report](../VALIDATION.md).
