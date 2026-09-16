# Team Brain

Keep shared project decisions, their reasoning, and the identity of the teammate who recorded them.

## Run locally

From the repository root:

```bash
cd cookbook/examples/team_brain
uv venv --python 3.14
source .venv/bin/activate
uv pip install -r requirements.txt
export OPENAI_API_KEY="your-openai-api-key"
python demo.py
```

A downloaded example uses the same commands after changing into its directory.
`requirements.txt` lists the runtime dependencies; no uv project is needed. Export
credentials in your shell. On Windows, activate with `.venv\Scripts\Activate.ps1`.
Model calls use `openai:gpt-5.6`.

## What to try

Alice records the onboarding checklist decision and maintenance reasoning. Bob
records the Friday user test and why it matters. The librarian reads the shared
log and answers with both authors. Each saved JSON record contains an ID, project,
decision, reasoning, author, and timestamp.

```bash
python demo.py --recall-only
```

This fresh process recalls the persisted log. Try "What did we decide for
Onboarding, why, and who decided?" Conflicting decisions remain separate records
with their authors and timestamps. Record a new correction explicitly.

## Storage and identity

`tmp/team_brain.db` stores sessions and the shared `team-brain` FileSystem namespace.
`decisions.jsonl` is the durable decision log. JSON encoding keeps newlines or an
embedded author claim inside a decision field from becoming another record.
Only the server-assigned `author` field establishes attribution. The librarian's
filesystem tools are read-only; the custom `remember` tool is the write surface.

All authorized teammates share this log. Keep personal information out of it;
there are no personal learning stores. The demo's `alice` and `bob` strings are
trusted local inputs, **not authentication proof**. Re-running the capture demo
adds new timestamped records. Relevant records are sent to OpenAI for answers.

## AgentOS and MCP

Export `JWT_VERIFICATION_KEY` as your trusted issuer's PEM RSA public key, then:

```bash
python team_brain.py
```

Use `http://127.0.0.1:7777/mcp` with a client that sends
`Authorization: Bearer <signed JWT>`. The JWT needs audience `team-brain`, a
nonempty `sub`, and suitable scopes for any REST routes you use (for example
`agents:team-brain:run`). The custom MCP endpoint grants shared-log access to
verified callers from that issuer. Give tokens only to participating teammates.

The two MCP tools are `remember(project, decision, reasoning)` and
`recall(question)`. `user_id` is hidden from the client schema and injected by
Agno from the verified JWT subject. Missing identity is rejected. The server
requires its verification key; importing without one exposes no ASGI app. There
are no embedded credentials or startup token-printing routines.

The log is shared even though AgentOS uses per-user session isolation. Use a
trusted issuer and HTTPS before remote exposure. This example provisions neither.
SQLite is for local use; use Postgres for production.

## Extend it

Add a project filter to recall, or a separate review step before recording a
team-wide decision. Preserve server-assigned authorship in either extension.

## Validate

From this example directory:

```bash
uv pip install pytest pytest-asyncio
python -m pytest test_contracts.py -q
```

See [TEST_LOG.md](TEST_LOG.md) for measured results and limitations. To check the
checkout instead of the published package, prefix the command with
`PYTHONPATH=../../../libs/agno` while running from this directory. The source
revision is recorded in the collection's [validation report](../VALIDATION.md).
