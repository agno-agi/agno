# Claude and Codex AgentOS readiness checks

This is a local, two-process integration fixture. AgentOS replicas use shared
Postgres and Redis, separate workspaces and separate SDK homes. The native SDKs
make real model calls. It does not establish host or tenant security isolation.

`serve.py` configures one provider per replica with a durable queue. `tools.py`
is a local MCP server that records receipts and can wait at a controllable gate.
`verify.py` submits HTTP requests, disconnects streams, cancels through another
replica, kills an owned worker process group and verifies stored results.

`ledger.py` counts every native SDK submission before it executes, including
adapter fallback and worker retries. The shared SQLite ledger is test control
infrastructure only; the AgentOS data and durable job queue use Postgres.

## Setup

Use the repository development environment with the native Claude/Codex SDKs,
MCP 2.x, psycopg, Redis and HTTPX installed. Start only the dedicated test services:

```bash
docker compose -f cookbook/frameworks/reliability/compose.yaml up -d --wait
```

Postgres binds loopback port 5543 and Redis binds loopback port 6387. The credentials
in compose.yaml are disposable local test credentials. Do not expose these ports.

Provision authenticated SDK homes under a private directory, with this layout:

```text
HARNESS_AUTH_ROOT/
  claude/a/
  claude/b/
  codex/a/
  codex/b/
```

Authenticate each using `CLAUDE_CONFIG_DIR` or `CODEX_HOME`, respectively, or
provision only your existing authentication material. Do not copy transcript,
project or session directories. The controller defaults to
`.context/harness-reliability/auth`; an exported `HARNESS_AUTH_ROOT` overrides it.
Never commit credentials or copy the whole user SDK home into the fixture.

Initialize `.context/harness-reliability/state.json` with the following shape.
Choose a future UTC deadline. Preserve this file and `ledger.sqlite` between
batches; never reset the live-call budget during one acceptance exercise.

```json
{
  "deadline_utc": "REPLACE_WITH_UTC_DEADLINE",
  "live_turn_budget": {"limit": 200, "reserved_attempts": 0},
  "stage": "build_test_kit"
}
```

## Verify

```bash
python cookbook/frameworks/reliability/verify.py --cases smoke --concurrency 1
python cookbook/frameworks/reliability/verify.py --concurrency 4
python cookbook/frameworks/reliability/verify.py --cases crash --attempts 2
python cookbook/frameworks/reliability/verify.py --cases concurrency --concurrency 1
python cookbook/frameworks/reliability/verify.py --cases concurrency --concurrency 8
# Negative probes record failures as evidence; inspect TEST_LOG.md.
python cookbook/frameworks/reliability/verify.py --cases active_reconnect,live_reconnect,tool_error,retention
# Run separately from the soak: Redis outage stops the dedicated test service.
python cookbook/frameworks/reliability/verify.py --cases same_session,redis_outage
# Only after preflight; keeps the same replica processes alive for up to eight hours.
python cookbook/frameworks/reliability/soak.py
```

Use `--provider claude` or `--provider codex` to select one provider. A lock prevents
concurrent controllers from overlapping. Native submission reservations are atomic
across all replica processes and survive crashes. The hard limit is 200 SDK turns;
it counts user-turn submissions, not every internal model/tool round trip.

Each batch creates a new Postgres schema and writes per-case evidence, replica
logs and a source manifest under `.context/harness-reliability/`. Failed cases
remain recorded. Diagnose a failure before repeating its scenario.

The tests distinguish:

- **Background acknowledgement:** durable HTTP 202 arrives before a held tool finishes.
- **Reconnect:** close SSE mid-tool, then obtain subsequent indexed events through
  the other replica after completion.
- **Live reconnect:** reconnect through the other replica while the tool is still
  held, then release it and require the terminal event.
- **Retention:** expire only a completed run's Redis keys and require stored event
  replay, including its tool result. This is stricter than polling run history.
- **Same session:** overlap two submissions and require both saved run records to
  survive. This does not prove a linear native conversation.
- **Redis outage:** stop only the test Redis after a run completes; require Postgres
  polling and an explicit SSE transport error. Restore Redis in `finally`.
- **Cancel:** cancel through the replica that did not execute the held tool.
- **Sessions:** preserve a synthetic fact while moving between SDK homes. Claude
  must retain its native session ID. Codex records whether it resumed or used
  Agno history in a new native thread; recall alone is not native continuity.
- **Idempotency:** duplicate accepted submissions return the same run and cause one receipt.
- **Crash:** kill the executing process group after a receipt. One allowed attempt
  must fail visibly without re-execution; two allowed attempts may repeat that
  receipt and must recover within the configured bounds.
- **Concurrency:** all 1, 4 or 8 tool calls reach a held checkpoint before release,
  proving simultaneous execution rather than merely simultaneous submissions.

Codex keeps the read-only sandbox and `deny_all` escalation policy. Only the
synthetic `fixture.checkpoint` tool is explicitly approved in its MCP configuration.
An MCP approval denial is retained as negative-test evidence; inspect tool results
as well as run status. See the official [MCP configuration reference](https://learn.chatgpt.com/docs/extend/mcp?surface=cli).

## Limits and cleanup

The paced soak samples longevity and idle-to-burst behavior, not continuous peak
throughput. Its default nine waves reserve 78 turns, plus six initial fault probes;
the shared budget includes every earlier batch. A minute-by-minute health and API
parent RSS sample does not measure the complete native SDK process tree.

A successful initial batch does not by itself establish an overnight soak, Redis event-TTL
fallback, authorization isolation, metrics, step replay, inbound AgentOS MCP/Slack,
or cross-machine failover. Those require separate evidence in the readiness report.
The existing Postgres fencing tests cover storage fault injection independently
of real provider runs. No framework defaults are changed by this fixture.

The SDK instrumentation is confined to test replica processes. Original credential
homes and other Docker applications must remain untouched. On completion, stop
only this Compose project. Delete its volumes only after retaining needed evidence:

```bash
docker compose -f cookbook/frameworks/reliability/compose.yaml down
```

See [TEST_LOG.md](TEST_LOG.md) for recorded results. Do not interpret an unexecuted
scenario or a green process exit without evidence as a pass.
