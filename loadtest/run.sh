#!/usr/bin/env bash
# One-command load test: bring up topology, run a phase, drain, reconcile.
#   ./run.sh up                       # build + start 2 replicas + pg + redis + lb
#   ./run.sh phase bounded 500 200    # phase name, n, concurrency
#   ./run.sh chaos-kill               # kill a replica mid-load (run in another shell)
#   ./run.sh down
set -euo pipefail
cd "$(dirname "$0")"
CF="docker-compose.yml"

wait_healthy() {
  echo "waiting for LB..."
  for _ in $(seq 1 60); do
    if curl -sf http://localhost:7777/health >/dev/null 2>&1 || curl -sf http://localhost:7777/ >/dev/null 2>&1; then
      echo "LB up"; return 0
    fi
    sleep 2
  done
  echo "LB did not come up"; docker compose -f "$CF" logs --tail=40; exit 1
}

case "${1:-}" in
  up)
    docker compose -f "$CF" up --build -d postgres redis replica1 replica2 lb
    wait_healthy ;;
  ui)
    # Multi-worker durable AgentOS for the AgentOS UI + real-time worker tracing.
    # Serves the single durable-agent (durable_ui.py) across 2 replicas behind the
    # LB. Point the AgentOS UI at http://localhost:7777 (agent id: durable-agent).
    # Watch which worker runs each job with:  ./run.sh trace
    echo "=== durable multi-worker AgentOS (UI) — 2 replicas + LB, real model ==="
    APP_MODULE=durable_ui MODEL=${MODEL:-real} \
      docker compose -f "$CF" up --build -d postgres redis replica1 replica2 lb
    wait_healthy
    echo "UI target: http://localhost:7777   (agent id: durable-agent)"
    echo "per-replica: replica1 :7801 · replica2 :7802"
    echo "watch workers live:  ./run.sh trace" ;;
  trace)
    # Live combined worker log: each replica prints [replicaN] CLAIMED/COMPLETED
    # run=<id>, so you see which worker handled each background run in real time.
    echo "=== live worker trace (Ctrl-C to stop) ==="
    docker compose -f "$CF" logs -f replica1 replica2 2>&1 \
      | grep --line-buffered -E "CLAIMED|COMPLETED|POST /agents|Job queue worker|PAUSED|continue" ;;
  phase)
    phase="${2:?phase}"; n="${3:-500}"; c="${4:-200}"
    echo "=== driving phase=$phase n=$n concurrency=$c ==="
    python driver.py --phase "$phase" --n "$n" --concurrency "$c"
    echo "draining 45s..."; sleep 45
    echo "=== reconcile ==="
    PG_DSN="postgresql://ai:ai@localhost:5533/ai" python reconcile.py ;;
  e2e)
    # Full feature suite (agents/teams/workflows: durable, SSE, WS, HITL,
    # cancel, error-persist, workflow-agent) -> results.json + report.html
    echo "=== E2E feature suite (real model) ==="
    BASE_URL=http://localhost:7777 PG_DSN="postgresql://ai:ai@localhost:5533/ai" MODEL=real python e2e.py
    python report.py
    echo "open report.html for the visual dashboard"
    command -v open >/dev/null && open report.html || true ;;
  stress-up)
    # Bring up a STUB-model stack tuned for the adversarial suites (stress +
    # distributed): retry budget, small depth for the 429 test, small lock-grace,
    # per-replica ports for cross-replica tests.
    MODEL=stub MAX_ATTEMPTS=${MAX_ATTEMPTS:-2} MAX_QUEUE_DEPTH=${MAX_QUEUE_DEPTH:-20} \
      LOCK_GRACE=${LOCK_GRACE:-35} TIMEOUT_SECONDS=${TIMEOUT_SECONDS:-15} \
      docker compose -f "$CF" up --build -d postgres redis replica1 replica2 lb
    wait_healthy ;;
  stress)
    # Adversarial suite: crash-recovery, concurrency races, malformed input.
    # NEEDS a stub stack: ./run.sh stress-up  first. (Destructive: kills a replica.)
    echo "=== STRESS suite (stub model) ==="
    BASE_URL=http://localhost:7777 PG_DSN="postgresql://ai:ai@localhost:5533/ai" \
      MODEL=stub MAX_ATTEMPTS=${MAX_ATTEMPTS:-2} MAX_QUEUE_DEPTH=${MAX_QUEUE_DEPTH:-20} \
      MAX_CONCURRENCY=${MAX_CONCURRENCY:-8} COMPOSE="$CF" python stress.py
    RESULTS=stress_results.json REPORT=stress_report.html python report.py
    echo "open stress_report.html"
    command -v open >/dev/null && open stress_report.html || true ;;
  distributed)
    # Distributed / multi-replica suite: cross-replica resume, redis-flap,
    # retryable-timeout(#7), stream-cancel, same-session clobber. NEEDS a stub
    # stack with per-replica ports: ./run.sh stress-up first.
    echo "=== DISTRIBUTED suite (stub model, multi-replica) ==="
    BASE_URL=http://localhost:7777 R1=http://localhost:7801 R2=http://localhost:7802 \
      PG_DSN="postgresql://ai:ai@localhost:5533/ai" MODEL=stub MAX_ATTEMPTS=${MAX_ATTEMPTS:-2} \
      COORD_REDIS_URL="redis://localhost:6380" \
      COMPOSE="$CF" python distributed.py
    RESULTS=distributed_results.json REPORT=distributed_report.html python report.py
    echo "open distributed_report.html"
    command -v open >/dev/null && open distributed_report.html || true ;;
  chaos-kill)
    echo "hard-killing replica2..."; docker compose -f "$CF" kill replica2
    echo "killed. In ~lock_grace+poll seconds its runs must be reclaimed or failed visibly."
    echo "restart with: docker compose -f $CF up -d replica2" ;;
  chaos-redis)
    echo "pausing redis 10s..."; docker compose -f "$CF" pause redis; sleep 10
    docker compose -f "$CF" unpause redis; echo "redis back" ;;
  logs)   docker compose -f "$CF" logs -f "${2:-}" ;;
  down)   docker compose -f "$CF" --profile chaos down -v ;;
  *) echo "usage: $0 {up|e2e|phase <name> <n> <c>|chaos-kill|chaos-redis|logs|down}"; exit 1 ;;
esac
