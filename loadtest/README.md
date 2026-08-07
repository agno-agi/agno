# Job Queue Load Test (Docker-only, no k6)

Everything runs in Docker Compose + a Python asyncio driver. No k6, no external SaaS.

## Topology
`nginx LB (:7777)` → `replica1` + `replica2` (round-robin, non-sticky) → shared `postgres` + `redis`.
Two replicas + non-sticky LB is what exercises the cross-replica durable/streaming paths.

## Prereqs
- Docker + Compose (you have v2.38).
- **`OPENAI_API_KEY` exported** — the default uses the REAL model (OpenAIResponses/gpt-5.5) for prod-fidelity E2E.
  `export OPENAI_API_KEY=sk-...`  (compose passes it into both replicas).
- Host Python with `httpx` + `psycopg` for the driver/reconciler:
  `pip install httpx "psycopg[binary]"`  (or use .venvs/demo which has both).

## Model & scale
Real model end-to-end by default → **real cost + provider rate limits**. Keep it MODEST:
- prompts are one short sentence (bounded generation),
- default runs ~50–200 concurrent, not thousands (avoids OpenAI RPM 429s muddying the queue signal).
- `MODEL=stub ./run.sh up` swaps to the free offline model for pure throughput ramps to thousands.

## Files
| file | role |
|------|------|
| `app.py` | AgentOS: agent+team+workflow, REAL model (or `MODEL=stub`), `QueueConfig(durable=True, redis=...)` |
| `stub_model.py` | optional offline model (`MODEL=stub`); input-driven latency (`sleep=2`, `fail`, `cpu`) — no OpenAI |
| `Dockerfile` / `docker-compose.yml` / `nginx.conf` | 2 replicas + pg + redis + LB (+ toxiproxy, profile `chaos`) |
| `driver.py` | async load driver: submit/poll/stream, phases, writes `client_ledger.jsonl` |
| `reconcile.py` | diffs ledger vs DB run rows + queue rows; asserts the 4 invariants |
| `run.sh` | up / phase / chaos / down orchestration |

## E2E feature suite (one command → visual report)
Covers, across agents / teams / workflows: durable background (202→poll→COMPLETED),
SSE streaming + mid-stream disconnect, WebSocket streaming (workflows), HITL tool
confirmation (PAUSED→/continue→COMPLETED), run cancellation, error persistence, and
the WorkflowAgent orphan-run check.
```bash
cd loadtest
export OPENAI_API_KEY=sk-...
./run.sh up          # start topology (2 replicas + pg + redis + LB)
./run.sh e2e         # runs all feature tests -> results.json + report.html (auto-opens)
```
`report.html` is a color-coded dashboard: green PASS / red FAIL / yellow WARN, a
summary banner, and expandable evidence per test. Latest run: **15/15 PASS**.

| feature | agents | teams | workflows |
|---------|:--:|:--:|:--:|
| durable background (run persistence) | ✅ | ✅ | ✅ |
| SSE stream + disconnect | ✅ | ✅ | ✅ |
| WebSocket stream | — | — | ✅ |
| HITL (tool confirmation → continue) | ✅ | — | — |
| run cancellation | ✅ | ✅ | ✅ |
| error persistence | ✅ | ✅ | ✅ |
| WorkflowAgent orphan check | — | — | ✅ |

## Quick start (load phases)
```bash
cd loadtest
export OPENAI_API_KEY=sk-...        # required for the real model
./run.sh up                        # build + start everything (~1-2 min first build)

# Phase 1 — Bounded (cap holds, overflow honest) — MODEST scale for real model
MAX_CONCURRENCY=8 ./run.sh phase bounded 200 50

# Phase 0.1 — Idempotency race (must dedupe to 1 run)
./run.sh phase idempotency 100 50

# Depth -> 429s (fills the queue; short real calls)
MAX_QUEUE_DEPTH=50 ./run.sh phase depth 300 100

# Streaming + random disconnect
COMPONENT=agents ./run.sh phase stream 60 30

# For big throughput ramps without cost, switch to the stub:
#   MODEL=stub ./run.sh up && ./run.sh phase bounded 3000 500

./run.sh down
```
`COMPONENT=agents|teams|workflows` selects what to hit (default agents).
Sweep the cap: `MAX_CONCURRENCY=1 ./run.sh up` (rebuild env) then re-run bounded.

## Phase 2 — Durability under chaos
In one shell, start sustained load:
```bash
./run.sh phase bounded 1000 200 &
```
In another, inject failure mid-flight, then reconcile:
```bash
./run.sh chaos-kill        # kill -9 replica2
# ... wait lock_grace+poll ...
docker compose -f docker-compose.yml up -d replica2   # bring it back
python reconcile.py        # assert: every accepted run terminal, none stuck
```
`./run.sh chaos-redis` flaps Redis for 10s (runs must still complete durably).

## The invariant that matters most
`reconcile.py` asserts **count(202 accepted) == count(reached terminal)** and **zero run rows stuck RUNNING/PENDING** after drain. That single check catches lost runs, stuck-RUNNING (the str-status / heartbeat-orphan / WatchError bugs), and orphan runs (the WorkflowAgent regression). If it prints `PASS`, durability held for that phase.

## Mapping to the known findings (Phase 0 gates)
- `phase idempotency` → the missing-index / idempotency-race dedup bug.
- `phase stream` with disconnects → tail lifecycle, index monotonicity, no silent-empty.
- `phase bounded` + `chaos-kill` at `MAX_ATTEMPTS=1` → stuck-RUNNING bugs surface as reconciler FAIL.
- `COMPONENT=workflows` + the WorkflowAgent app variant → the orphan-run regression.

## Notes / knobs
- All `QueueConfig` dials are env vars in compose (`MAX_CONCURRENCY`, `LOCK_GRACE`, `MAX_ATTEMPTS`, `MAX_QUEUE_DEPTH`, `TIMEOUT_SECONDS`).
- Redis runs with AOF `everysec` (the documented durability recommendation).
- toxiproxy (compose profile `chaos`) is included for deterministic PG/Redis latency+partition if you want finer fault injection than pause/kill.
