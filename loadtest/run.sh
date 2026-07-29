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
