"""
Manual Trigger Example

This example demonstrates how to manually trigger schedules.
Manual triggers bypass the normal cron timing and execute immediately.

This is useful for:
- Testing schedules before their scheduled time
- On-demand execution of recurring tasks
- Integration with external event systems

Requirements:
    pip install agno[scheduler]

Run:
    python cookbook/05_agent_os/scheduler/05_manual_trigger.py

Then:
    1. Create a schedule (see output for curl command)
    2. Trigger it manually (see output for curl command)
"""

import time

import httpx
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS

# Create an agent that can be triggered on demand
notification_agent = Agent(
    id="notification-agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="""You are a notification assistant.
    Generate a brief notification message based on the input.""",
)

# Create database and AgentOS
db = SqliteDb(db_file="manual_trigger.db")
agent_os = AgentOS(
    agents=[notification_agent],
    db=db,
    enable_scheduler=True,
    scheduler_poll_interval=30,  # Longer interval since we'll trigger manually
)


def demo_manual_trigger():
    """Demonstrate creating and manually triggering a schedule."""
    base_url = "http://localhost:7777"

    # Wait for server to start
    time.sleep(2)

    print("\n" + "=" * 60)
    print("Manual Trigger Demo")
    print("=" * 60)

    # Step 1: Create a schedule (set to run far in the future)
    print("\n1. Creating a schedule (runs daily at midnight)...")
    schedule_data = {
        "name": "daily-notification",
        "description": "Send daily notification",
        "endpoint": "/agents/notification-agent/runs",
        "method": "POST",
        "payload": {"message": "Generate a notification for the team."},
        "cron_expr": "0 0 * * *",  # Midnight - won't run automatically soon
        "timezone": "UTC",
    }

    try:
        response = httpx.post(
            f"{base_url}/schedules",
            json=schedule_data,
            timeout=10.0,
        )
        if response.status_code == 201:
            schedule = response.json()
            schedule_id = schedule["id"]
            print(f"   Created schedule: {schedule['name']} (ID: {schedule_id})")
            print(f"   Next scheduled run: {schedule.get('next_run_at')}")

            # Step 2: Manually trigger the schedule
            print("\n2. Manually triggering the schedule...")
            trigger_response = httpx.post(
                f"{base_url}/schedules/{schedule_id}/trigger",
                timeout=30.0,
            )
            if trigger_response.status_code == 200:
                print("   Schedule triggered successfully!")
                print(f"   Response: {trigger_response.json()}")
            else:
                print(f"   Trigger failed: {trigger_response.text}")

            # Step 3: Check run history
            print("\n3. Checking run history...")
            time.sleep(5)  # Wait for execution
            runs_response = httpx.get(
                f"{base_url}/schedules/{schedule_id}/runs",
                timeout=10.0,
            )
            if runs_response.status_code == 200:
                runs = runs_response.json()
                print(f"   Total runs: {runs['total']}")
                for run in runs["runs"]:
                    print(f"   - Run {run['id']}: {run['status']}")

        elif response.status_code == 400:
            print("   Schedule already exists, fetching it...")
            # Get existing schedule
            list_response = httpx.get(f"{base_url}/schedules", timeout=10.0)
            if list_response.status_code == 200:
                schedules = list_response.json()["schedules"]
                for s in schedules:
                    if s["name"] == "daily-notification":
                        schedule_id = s["id"]
                        print(f"   Found: {s['name']} (ID: {schedule_id})")

                        # Trigger it
                        print("\n   Triggering existing schedule...")
                        trigger_response = httpx.post(
                            f"{base_url}/schedules/{schedule_id}/trigger",
                            timeout=30.0,
                        )
                        if trigger_response.status_code == 200:
                            print("   Triggered successfully!")
                        break

    except Exception as e:
        print(f"   Error: {e}")

    print("\n" + "=" * 60)


if __name__ == "__main__":
    print("Starting AgentOS with manual trigger demo...")
    print("\nAPI Commands:")
    print("\n  Create schedule:")
    print("""    curl -X POST http://localhost:7777/schedules \\
      -H "Content-Type: application/json" \\
      -d '{
        "name": "my-schedule",
        "endpoint": "/agents/notification-agent/runs",
        "cron_expr": "0 0 * * *"
      }'""")

    print("\n  Trigger manually:")
    print("    curl -X POST http://localhost:7777/schedules/{id}/trigger")

    print("\n  View runs:")
    print("    curl http://localhost:7777/schedules/{id}/runs")

    # Run the demo in background after server starts
    import threading

    threading.Timer(3.0, demo_manual_trigger).start()

    app = agent_os.get_app()
    agent_os.serve(app, port=7777)
