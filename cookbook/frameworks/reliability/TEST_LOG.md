# Reliability fixture test log

## Initial preparation — 2026-10-10 (Europe/London)

### Existing agent, queue and replay regressions

**Status:** PASS

**Description:** Ran external-agent unit tests, queue-worker tests, database replay
fallback tests and background-stream tests before live execution.

**Result:** 345 passed in 32.08s. These include fakes and do not substitute for real
provider/multi-process verification. Log: `.context/harness-reliability/deterministic.log`.

### Real Postgres session fencing

**Status:** PASS

**Description:** Ran `test_external_session_fencing.py` against the dedicated
Postgres 18 service, using sync and async adapters.

**Result:** 10 passed in 0.78s, including stale-worker rejection, session-write
rollback and missing/foreign session guards. Log: `postgres-fencing.log`.

### Atomic turn budget and deadline

**Status:** PASS

**Description:** Raced 16 reservations with one available turn and verified that
an expired deadline prevents any native submission reservation.

**Result:** Two tests pass. Exactly one concurrent reservation succeeds at 199
used turns; the persisted total remains 200.

### First live tool preflight

**Status:** FAIL

**Description:** Both providers completed without a real fixture tool result.

**Result:** Test fixture imported FastMCP from its MCP 1.x location, but the test
environment runs MCP 2.x. Direct MCP initialization reproduced the fixture import
failure. Corrected the fixture to MCPServer and verified discovery plus a receipt
without a model call. Both failed native submissions remain budgeted and recorded.

### Live tool preflight after MCP fixture correction

**Status:** PASS (Claude), FAIL (Codex)

**Description:** Claude executed and persisted the real tool result. Codex attempted
the write tool but its restrictive approval policy denied execution.

**Result:** Codex returned a COMPLETED run whose tool result contained an approval
error and whose `tool_call_error` was unset. Record this as a configuration
requirement and a candidate tool-error mapping defect; no framework fix was made.
The synthetic tool now has explicit per-tool approval, keeping other escalation
requests denied. The corrected Codex preflight passed in 8.2s.

### Full two-replica matrix

**Status:** PASS

All eight cases passed for each provider (16 total): smoke, background, disconnect,
cancel, session recall, idempotency, default crash policy and four simultaneously
held tools. Inspect `matrix-attempts1.log` and per-case JSON for timing and native
session IDs. Codex recall is not a claim of exact native transcript continuity.
Five native submissions were reserved before this batch. Retry-enabled crash
and concurrency 1/8 batches also passed for both providers (six additional passes).
There were 51 cumulative native submissions before the soak.

Source: `0da9c9f80e` plus the new uncommitted reliability fixtures. Python 3.12.8,
Claude SDK 0.2.165 / claude-sonnet-5-5, Codex SDK 0.162.1 / gpt-5.6-luna.
Dedicated Postgres 18 and Redis 7 services; no unrelated services changed.

### Paced soak — in progress

**Status:** PENDING (not a completed pass)

Started 2026-10-09 23:25:49 UTC, planned end 2026-10-10 07:25:49 UTC.
Four persistent replica processes use the same isolated homes and shared test
infrastructure. Nine load waves cycle through 1, 4 and 8 simultaneous held tools,
with parent RSS and health sampled every minute. This is a paced longevity check,
not sustained peak-load benchmarking. Raw evidence is in `soak.log`,
`soak-resources.jsonl` and per-suite JSON; no eight-hour result is claimed yet.

### Background submission followed by late streaming

**Status:** FAIL (Claude and Codex)

A background run submitted with `stream=false` reaches a real held tool. While it
is still RUNNING, `/resume` returns a replay metadata frame with zero events and
"Run completed but no events stored." The tested workaround is to request
`background=true, stream=true` initially and disconnect that stream. Polling a
nonstream background run remains available. Evidence: `active_reconnect-fault-probe.json`.

### Native tool-error mapping

**Status:** PASS (Claude), FAIL (Codex)

A real MCP tool records its receipt and then raises. Claude persists
`tool_call_error=true`; Codex persists the tool's error text with the flag unset.
The model itself correctly reports the failure, so a completed outer run alone is
not a defect. Consumers cannot rely on Codex's tool-error flag for this case.
Evidence: `failed-tool-run.json`. No product fix was made.

### Event retention probe

**Status:** FAIL (fixture precondition; product result unverified)

The first probe used a nonstream background submission, which created no Redis
event keys. It therefore never exercised expiration. Those failures are retained.
The fixture now starts from a verified streaming run before expiring only that
run's keys; the corrected probe still needs execution after the active soak.
