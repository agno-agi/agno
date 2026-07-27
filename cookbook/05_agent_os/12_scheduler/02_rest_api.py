"""
Manage Schedules over REST
==========================

Use raw HTTP to create, list, read, update, enable, disable, trigger, page
through run history, and delete a schedule served by 01_run_in_agentos.py.

Prerequisites: 01_run_in_agentos.py running with OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/12_scheduler/02_rest_api.py
Try: Inspect the data and meta objects returned for run-history pages 1 and 2
"""

import os

import httpx

# ---------------------------------------------------------------------------
# Create REST Client Helpers
# ---------------------------------------------------------------------------

BASE_URL = os.getenv("AGENT_OS_BASE_URL", "http://127.0.0.1:7777")
AGENT_ID = "scheduled-greeter"
SCHEDULE_NAME = "rest-api-greeting"


def delete_existing(client: httpx.Client) -> None:
    """Remove an earlier copy so the walkthrough is repeatable."""
    response = client.get("/schedules", params={"limit": 100, "page": 1})
    response.raise_for_status()
    for schedule in response.json()["data"]:
        if schedule["name"] == SCHEDULE_NAME:
            delete_response = client.delete(f"/schedules/{schedule['id']}")
            delete_response.raise_for_status()


def trigger(client: httpx.Client, schedule_id: str) -> dict:
    """Trigger one schedule and require a completed executor record."""
    response = client.post(f"/schedules/{schedule_id}/trigger")
    response.raise_for_status()
    run = response.json()
    if run["status"] != "success":
        raise RuntimeError(f"Triggered run ended with {run['status']}")
    return run


# ---------------------------------------------------------------------------
# Run REST Schedule Lifecycle
# ---------------------------------------------------------------------------


def run_rest_lifecycle() -> None:
    """Exercise the complete schedule REST lifecycle."""
    with httpx.Client(base_url=BASE_URL, timeout=180.0) as client:
        health_response = client.get("/health")
        health_response.raise_for_status()
        config_response = client.get("/config")
        config_response.raise_for_status()
        config = config_response.json()
        delete_existing(client)

        create_response = client.post(
            "/schedules",
            json={
                "name": SCHEDULE_NAME,
                "cron_expr": "0 0 1 1 *",
                "endpoint": f"/agents/{AGENT_ID}/runs",
                "description": "A schedule managed through raw HTTP.",
                "payload": {
                    "message": "Confirm this manually triggered scheduler run.",
                    "session_id": "rest-scheduler-session",
                },
                "timezone": "UTC",
                "timeout_seconds": 120,
                "max_retries": 1,
                "retry_delay_seconds": 5,
            },
        )
        create_response.raise_for_status()
        schedule = create_response.json()
        schedule_id = schedule["id"]

        try:
            list_response = client.get(
                "/schedules",
                params={"limit": 1, "page": 1},
            )
            list_response.raise_for_status()
            listed = list_response.json()
            if set(listed) != {"data", "meta"} or listed["meta"]["page"] != 1:
                raise RuntimeError("Schedule listing did not use data/meta pagination")

            detail_response = client.get(f"/schedules/{schedule_id}")
            detail_response.raise_for_status()
            if detail_response.json()["name"] != SCHEDULE_NAME:
                raise RuntimeError("Schedule detail returned the wrong row")

            update_response = client.patch(
                f"/schedules/{schedule_id}",
                json={
                    "description": "Updated through PATCH.",
                    "cron_expr": "0 9 1 1 *",
                },
            )
            update_response.raise_for_status()
            updated = update_response.json()
            if updated["cron_expr"] != "0 9 1 1 *":
                raise RuntimeError("PATCH did not persist cron_expr")

            disable_response = client.post(f"/schedules/{schedule_id}/disable")
            disable_response.raise_for_status()
            if disable_response.json()["enabled"]:
                raise RuntimeError("Schedule remained enabled")

            enable_response = client.post(f"/schedules/{schedule_id}/enable")
            enable_response.raise_for_status()
            if not enable_response.json()["enabled"]:
                raise RuntimeError("Schedule remained disabled")

            first_run = trigger(client, schedule_id)
            second_run = trigger(client, schedule_id)

            first_page_response = client.get(
                f"/schedules/{schedule_id}/runs",
                params={"limit": 1, "page": 1},
            )
            first_page_response.raise_for_status()
            first_page = first_page_response.json()

            second_page_response = client.get(
                f"/schedules/{schedule_id}/runs",
                params={"limit": 1, "page": 2},
            )
            second_page_response.raise_for_status()
            second_page = second_page_response.json()

            if first_page["meta"]["total_count"] < 2:
                raise RuntimeError("Expected two persisted trigger records")
            if first_page["meta"]["page"] != 1 or second_page["meta"]["page"] != 2:
                raise RuntimeError("Run-history pagination did not preserve page")
            if not first_page["data"] or not second_page["data"]:
                raise RuntimeError("Expected one run on each requested history page")
            page_ids = {
                first_page["data"][0]["id"],
                second_page["data"][0]["id"],
            }
            if len(page_ids) != 2:
                raise RuntimeError("History pages returned the same run")

            print(f"Health: {health_response.json()['status']}")
            print(f"AgentOS: {config['os_id']}")
            print(f"Agent: {config['agents'][0]['id']}")
            print(f"Created: {schedule_id}")
            print(f"Updated cron: {updated['cron_expr']}")
            print(f"Triggered runs: {first_run['id']}, {second_run['id']}")
            print(f"History keys: {sorted(first_page)}")
            print(
                "History pages: "
                f"{first_page['meta']['page']}, {second_page['meta']['page']}"
            )
            print(f"History total: {first_page['meta']['total_count']}")
        finally:
            delete_response = client.delete(f"/schedules/{schedule_id}")
            if delete_response.status_code not in {204, 404}:
                delete_response.raise_for_status()


if __name__ == "__main__":
    run_rest_lifecycle()
