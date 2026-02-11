"""Using the scheduler REST API endpoints directly.

This example demonstrates:
- Creating schedules via POST /schedules
- Listing schedules via GET /schedules
- Updating via PATCH /schedules/{id}
- Enable/disable via POST /schedules/{id}/enable and /disable
- Manual trigger via POST /schedules/{id}/trigger
- Viewing run history via GET /schedules/{id}/runs
- Deleting via DELETE /schedules/{id}

Requires: a running AgentOS server with scheduler=True

    .venvs/demo/bin/python cookbook/05_agent_os/scheduler/scheduler_with_agentos.py

Then in another terminal:

    .venvs/demo/bin/python cookbook/05_agent_os/scheduler/rest_api_schedules.py
"""

import httpx

BASE_URL = "http://127.0.0.1:7777"

client = httpx.Client(base_url=BASE_URL, timeout=30)


def main():
    # =========================================================================
    # 1. Create a schedule
    # =========================================================================
    print("=== Create Schedule ===\n")
    resp = client.post(
        "/schedules",
        json={
            "name": "api-demo-schedule",
            "cron_expr": "*/5 * * * *",
            "endpoint": "/agents/greeter/runs",
            "description": "Created via REST API",
            "payload": {"message": "Hello from the REST API!"},
            "timezone": "UTC",
            "max_retries": 1,
            "retry_delay_seconds": 30,
        },
    )
    resp.raise_for_status()
    schedule = resp.json()
    schedule_id = schedule["id"]
    print(f"Created: {schedule['name']} (id={schedule_id})")
    print(f"  Cron: {schedule['cron_expr']}")
    print(f"  Next run: {schedule['next_run_at']}")

    # =========================================================================
    # 2. List all schedules
    # =========================================================================
    print("\n=== List Schedules ===\n")
    resp = client.get("/schedules")
    resp.raise_for_status()
    result = resp.json()
    schedules = result["data"]
    meta = result["meta"]
    print(
        f"Page {meta['page']} of {meta['total_pages']} (total: {meta['total_count']})\n"
    )
    for s in schedules:
        status = "enabled" if s["enabled"] else "disabled"
        print(f"  {s['name']} [{status}] -> {s['endpoint']}")

    # =========================================================================
    # 3. Get a single schedule
    # =========================================================================
    print("\n=== Get Schedule ===\n")
    resp = client.get(f"/schedules/{schedule_id}")
    resp.raise_for_status()
    detail = resp.json()
    print(f"  Name: {detail['name']}")
    print(f"  Cron: {detail['cron_expr']}")
    print(f"  Timezone: {detail['timezone']}")
    print(f"  Max retries: {detail['max_retries']}")

    # =========================================================================
    # 4. Update the schedule
    # =========================================================================
    print("\n=== Update Schedule ===\n")
    resp = client.patch(
        f"/schedules/{schedule_id}",
        json={
            "description": "Updated description via REST API",
            "cron_expr": "0 * * * *",
        },
    )
    resp.raise_for_status()
    updated = resp.json()
    print(f"  Description: {updated['description']}")
    print(f"  Cron: {updated['cron_expr']}")

    # =========================================================================
    # 5. Disable and re-enable
    # =========================================================================
    print("\n=== Disable/Enable ===\n")
    resp = client.post(f"/schedules/{schedule_id}/disable")
    resp.raise_for_status()
    print(f"  Disabled: enabled={resp.json()['enabled']}")

    resp = client.post(f"/schedules/{schedule_id}/enable")
    resp.raise_for_status()
    print(f"  Re-enabled: enabled={resp.json()['enabled']}")

    # =========================================================================
    # 6. Manual trigger
    # =========================================================================
    print("\n=== Manual Trigger ===\n")
    try:
        resp = client.post(f"/schedules/{schedule_id}/trigger")
        if resp.status_code == 200:
            trigger_result = resp.json()
            print(f"  Trigger result: status={trigger_result.get('status')}")
            print(f"  Run ID: {trigger_result.get('run_id')}")
        elif resp.status_code == 503:
            print("  Trigger returned 503 (scheduler executor not running yet)")
        else:
            print(f"  Trigger response: {resp.status_code} {resp.text}")
    except Exception as e:
        print(f"  Trigger timed out or failed: {type(e).__name__}")

    # =========================================================================
    # 7. View run history
    # =========================================================================
    print("\n=== Run History ===\n")
    resp = client.get(f"/schedules/{schedule_id}/runs", params={"limit": 5, "page": 1})
    resp.raise_for_status()
    result = resp.json()
    runs = result["data"]
    meta = result["meta"]
    if runs:
        print(f"Showing {len(runs)} of {meta['total_count']} total runs\n")
        for run in runs:
            print(
                f"  Run {run['id'][:8]}... status={run['status']} attempt={run['attempt']}"
            )
    else:
        print("  No runs yet (schedule hasn't been polled)")

    # =========================================================================
    # 8. Delete the schedule
    # =========================================================================
    print("\n=== Delete ===\n")
    resp = client.delete(f"/schedules/{schedule_id}")
    resp.raise_for_status()
    try:
        result = resp.json()
        print(f"  Deleted: {result}")
    except Exception:
        print(f"  Deleted successfully (status {resp.status_code})")

    print("\nDone.")


if __name__ == "__main__":
    main()
