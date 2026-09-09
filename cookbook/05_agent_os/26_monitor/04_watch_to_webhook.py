"""
Watch to Webhook
================

Deliver events to a plain HTTP endpoint instead of an agent. No model is called
-- this is the shape for when reacting to a change is mechanical.

Prerequisites: pip install agno watchfiles
Run: .venvs/demo/bin/python cookbook/05_agent_os/26_monitor/04_watch_to_webhook.py
Try: Run this file with --demo in another terminal
"""

import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

from agno.db.sqlite import SqliteDb
from agno.monitor import MonitorConfig, MonitorManager
from agno.os import AgentOS
from fastapi import FastAPI, Request

# ---------------------------------------------------------------------------
# Create Webhook AgentOS
# ---------------------------------------------------------------------------

WATCH_ROOT = Path("tmp/webhook_watch")
WEBHOOK_PATH = "/webhooks/monitor-events"

db = SqliteDb(id="watch-to-webhook", db_file="tmp/watch_to_webhook.db")
received: List[Dict[str, Any]] = []

base_app = FastAPI(title="Monitor Webhook", version="1.0.0")


@base_app.post(WEBHOOK_PATH)
async def monitor_events(request: Request) -> Dict[str, Any]:
    """Receive one event: the monitor's payload plus monitor_id, monitor_name, event, seq."""
    body = await request.json()
    received.append(body)
    print("Webhook received:")
    print(json.dumps(body, indent=2))
    return {"ok": True, "seq": body.get("seq")}


@base_app.get(WEBHOOK_PATH)
async def list_received() -> List[Dict[str, Any]]:
    return received


agent_os = AgentOS(
    name="Webhook OS",
    db=db,
    base_app=base_app,
    monitors=MonitorConfig(base_dir=str(WATCH_ROOT), poll_interval=2),
)
app = agent_os.get_app()


def ensure_monitor() -> None:
    WATCH_ROOT.mkdir(parents=True, exist_ok=True)
    manager = MonitorManager(db=db, base_dir=str(WATCH_ROOT))
    if manager.list(status=None):
        return
    monitor = manager.create(
        name="webhook-on-change",
        watch_path=".",
        endpoint=WEBHOOK_PATH,
        method="POST",
        payload={"source": "webhook-demo", "severity": "info"},
        persistent=True,
        max_events=200,
    )
    print(f"Watching {WATCH_ROOT} as monitor {monitor.id} -> {WEBHOOK_PATH}")


# ---------------------------------------------------------------------------
# Run Webhook AgentOS
# ---------------------------------------------------------------------------
# A non-run endpoint is admin-only when RBAC is enabled: a POST run endpoint is
# checked against <type>:run, and anything else has no per-resource scope to
# compare against.


def run_demo() -> None:
    """Touch a watched file, then print the JSON body the webhook received."""
    import httpx

    with httpx.Client(base_url="http://127.0.0.1:7777", timeout=30) as client:
        try:
            client.get("/health")
        except httpx.ConnectError:
            print("No AgentOS on http://127.0.0.1:7777.")
            print("Start it first, in another terminal:")
            print("    python cookbook/05_agent_os/26_monitor/04_watch_to_webhook.py")
            return

        before = len(client.get(WEBHOOK_PATH).json())

        target = WATCH_ROOT / "report.csv"
        target.parent.mkdir(parents=True, exist_ok=True)
        print(f"Touching {target}...")
        target.write_text("region,total\nemea,41200\n")

        print("Waiting for the webhook to be called...")
        for _ in range(40):
            time.sleep(2)
            bodies = client.get(WEBHOOK_PATH).json()
            if len(bodies) > before:
                print("\nWhat the webhook received:\n")
                print(json.dumps(bodies[-1], indent=2))
                return
        print("The webhook was never called.")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        run_demo()
        raise SystemExit
    ensure_monitor()
    agent_os.serve(app=app)
