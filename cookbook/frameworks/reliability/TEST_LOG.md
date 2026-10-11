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

### Paced soak — completed with failures

**Status:** FAIL (Claude load longevity), PASS (Codex load longevity)

Measured controller lifetime: 2026-10-09 23:25:49.886 UTC to 2026-10-10
07:25:50.666 UTC (28,800.78 seconds, including startup and cleanup). Nine paced
waves cycled through 1, 4 and 8 simultaneous held tools. Codex passed all nine;
Claude passed seven, then failed the final 4- and 8-run waves after replica A lost
OAuth authentication. The initial 1/4/8 matrix passed for both. This was not
continuous peak load: provider waves ran sequentially, with a quiet final hour.

All 490 health samples returned HTTP 200 for all four API replicas. Healthy API
processes did not imply working provider authentication. The cause of Claude's
refresh failure remains unresolved; a clean Claude eight-hour acceptance pass
cannot be claimed. Subsequent Claude probes are blocked by that authentication
failure. Do not use stale copied credentials to mask it.

The controller recorded seven failed checks: two late Claude load waves, three
confirmed behavior gaps described below, and two original retention fixture
precondition failures. That count is not seven distinct product defects.
Evidence: `state.json`, `soak.log`, `soak-resources.jsonl`, per-suite
`concurrency-*.json`, and `claude-wave7-auth-failure.json`.

### Extended deterministic fault coverage

**Status:** PASS

150 additional event-stream, lease, sweep, queue, fencing and startup cases passed.
Together with 345 initial cases and two budget tests, this is 497 unique
unit/deterministic checks, plus the 10 real Postgres tests above. An existing
unawaited AsyncMock warning remains recorded in `extended-faults.log`.
Repeated terminal-write checks overlap the initial suite and are not counted again.

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
run's keys. The corrected Codex probe FAILS: Redis keys existed, were expired, and
`/resume` returned zero events even though the completed run and real tool result
were persisted. Claude's corrected probe is BLOCKED by authentication. This is a
Codex live result; the shared source path suggests the same limitation for Claude,
but that inference is not a Claude live pass or failure.
Evidence: `codex-readiness_a4ce6a7203b04c0e/expired-transport-replay.json`.
Reproduce: `python cookbook/frameworks/reliability/verify.py --provider codex --cases retention`.


### Concurrent turns in one session

**Status:** FAIL (Codex), BLOCKED (Claude authentication)

Two background runs shared one Agno session. The first reached its held tool; the
second was accepted but later failed with `thread ... already has an active writer`.
The first completed with its real tool result. This differs from the independent
sessions used in the passing 1/4/8-load matrix. API routing to another replica does
not guarantee execution by that replica because workers claim shared queue jobs.
Serialize turns within a session for the POC; define queue/conflict behavior before
promising concurrent turns on the same conversation. Evidence: final-probe replica
logs and `inspection-run-29764051-a3ec-4505-b610-6cb92c2d4ea9.json`.
Reproduce: `python cookbook/frameworks/reliability/verify.py --provider codex --cases same_session`.

### Separate retries PR #10929 review

**Status:** FAIL (merge acceptance); passing subcases recorded separately

Tested exact head `92d3fcf250436dfa4d338e27af3e6f56aef4a6e0` through a read-only source
snapshot, leaving the checkout and overnight framework revision unchanged. 126
existing unit tests pass. Twelve separately budgeted live Codex SDK turns verify
native thread/run ID continuity through controlled failures. Direct and queued
streaming retries preserve the real tool record; nonstreaming retries complete
with zero persisted tools after a real tool ran in the earlier failed attempt.
A second reproduction retains the actual native MCP result items and changes only
the native result status/error, confirming the adapter drops items before retry.

Six real-Postgres worker contracts with synthetic adapter failures establish:
transient failures use six attempts for `max_attempts=2, retries=2`; permanent
`unauthorized` failures still execute twice across queue attempts; cancellation
during a 30-second backoff settles in approximately 0.6 seconds after one attempt.

Hold merge for preserving failed-attempt tool history in nonstreaming runs and
carrying permanent-error classification through persistence into queue retry
policy. Document the multiplicative retry budget and client handling of partial
streaming output. These tests do not simulate a real provider outage. No live
Claude retry or PR-head cross-process crash result is claimed. Private evidence:
`.context/pr10929/review.json`; original overnight results remain separate.


### Reconnect while running, and Redis outage

**Status:** PASS (Codex), BLOCKED (Claude authentication)

The corrected live-reconnect probe opens SSE through replica B while the tool is
held, then releases it and receives ordered indexed events through RunCompleted.
Its initial failure happened before reconnect: the model selected an unrelated
connected tool, which rejected the fixture arguments. That failure remains saved.
The prompt now names `mcp__fixture__checkpoint` exactly. Inspection also found a
potential fixture deadlock: release must follow subscription establishment, not
wait for a new event when the cursor is already current. Corrected probe passed in
5.32 seconds. Evidence: `live-reconnect-corrected.log` and its suite JSON.

The Redis outage probe passed in 10.92 seconds. A completed run remained pollable
from Postgres while the dedicated Redis was stopped, and `/resume` returned an
explicit SSE error. Redis was restored in `finally`. This does not test an outage
during an active model turn or recovery after Redis data loss.

## Final acceptance matrix

Framework revision: `0da9c9f80ef26aa7a917647f3c003b0459158ab4`; later fixture-only
commits preserve that production implementation. FAIL can describe a known
limitation or an environment failure; see the evidence above for the cause.
BLOCKED means not verified, not a claimed product failure. UNSUPPORTED means
outside the demonstrated contract.

| Scenario | Claude | Codex |
|---|---|---|
| Real tool receipt and persisted result | PASS | PASS |
| Background acknowledgement and polling | PASS | PASS |
| Initial SSE and cross-replica catch-up after completion | PASS | PASS |
| Reconnect through another replica while still running | BLOCKED: auth | PASS |
| Start nonstream background run, attach live SSE later | FAIL | FAIL |
| Replay after Redis event expiration | BLOCKED: auth | FAIL: zero stored events |
| Cross-replica session fact recall | PASS | PASS: bounded-history fallback |
| Exact native session continuity across isolated homes | PASS: native ID retained | UNSUPPORTED: new thread |
| Cross-replica cancellation | PASS | PASS |
| Duplicate submission idempotency | PASS | PASS |
| Crash with one allowed queue attempt | PASS: visible ERROR, one receipt | PASS: visible ERROR, one receipt |
| Crash with two allowed queue attempts | PASS: completed, two receipts | PASS: completed, two receipts |
| Exactly-once external effects under retry | UNSUPPORTED | UNSUPPORTED |
| Initial independent-session concurrency 1/4/8 | PASS | PASS |
| Eight-hour paced load longevity | FAIL: OAuth loss, seven of nine waves pass | PASS: nine of nine waves |
| Failed-tool error flag | PASS | FAIL: null flag |
| Concurrent turns within one session | BLOCKED: auth | FAIL: active writer conflict |
| Redis-down polling and explicit SSE error, completed run | BLOCKED: auth | PASS |
| Stale workers and persistence faults | PASS: deterministic/shared Postgres tests | PASS: deterministic/shared Postgres tests |
| Provider live turn during persistence outage | BLOCKED: not executed | BLOCKED: not executed |
| Metrics #10925 on tested revision | BLOCKED: absent | BLOCKED: absent |
| Step replay #10917 on tested revision | BLOCKED: absent | UNSUPPORTED: Claude-specific feature |
| Host/tenant isolation, inbound MCP/Slack, compaction/plugins | BLOCKED: not tested | BLOCKED: not tested |

#10917 merged during the soak but is absent from the tested revision. #10925 was
still open at final verification. Neither result is inferred from its PR status.

Final cumulative reservation count: **152/200**. Readiness used 140 (51 before
soak, 84 during soak, five after soak); the separate #10929 review used 12. Failed
and blocked-before-completion native submissions remain counted. Calls rejected
before native SDK submission, such as the same-session active-writer error, do not
consume a native-turn reservation. The ledger is retained and must not be reset.

Full `scripts/format.sh` and `scripts/validate.sh` passed after fixture changes;
Ruff, mypy (1114 Agno / 21 agnoctl files), and 13 quickstart pattern checks passed.
Unrelated formatter changes were restored. No product defects were fixed by this
readiness update. Raw evidence and private SDK homes remain outside Git.

## POC conditions and customer wording

Resolve and revalidate Claude credential refresh before relying on an unattended
Claude deployment. Request streaming initially, size the Redis retention window
for reconnect requirements, serialize turns within each session, and make external
effects idempotent before enabling queue retries. Fix or explicitly scope out
durable event replay and the Codex failed-tool flag. Hold #10929 for its two
separately reproduced retry issues. Re-test metrics and step replay on the actual
release candidate. Broader guarantees need the blocked scenarios above.

Suggested wording:

> AgentOS supports background runs, persisted run history and real tool results
> for Claude and Codex. Two-replica Postgres/Redis tests verified cancellation,
> reconnect from initially streamed runs, and configured crash recovery. Event
> catch-up currently depends on retained Redis events. Claude retained its native
> session across isolated replicas; Codex used history fallback when its native
> thread was unavailable. Retries can repeat external effects, so integrations
> need idempotency. Turns within a session should be serialized. Claude credential
> refresh, metrics, step replay and the pending agent-retry changes still need
> release acceptance before we promise the full reliability contract.
