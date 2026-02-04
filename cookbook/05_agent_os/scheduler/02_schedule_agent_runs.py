"""
Schedule Agent Runs Example

This example demonstrates scheduling regular agent runs.
The scheduler will automatically run the agent at specified times.

Requirements:
    pip install agno[scheduler]

Run:
    python cookbook/05_agent_os/scheduler/02_schedule_agent_runs.py
"""

import httpx
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS

# Create a daily report agent
report_agent = Agent(
    id="daily-reporter",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="""You are a daily report generator.
    Generate a brief summary of the current date and a motivational quote.""",
)

# Create a weather agent
weather_agent = Agent(
    id="weather-checker",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="""You are a weather information assistant.
    Provide a brief weather forecast (you can make up plausible weather).""",
)

# Create database and AgentOS
db = SqliteDb(db_file="scheduled_agents.db")
agent_os = AgentOS(
    agents=[report_agent, weather_agent],
    db=db,
    enable_scheduler=True,
    scheduler_poll_interval=10,
)


def create_schedules():
    """Create sample schedules after server starts."""
    base_url = "http://localhost:7777"

    schedules = [
        {
            "name": "daily-morning-report",
            "description": "Generate a daily morning report",
            "endpoint": "/v1/agents/daily-reporter/runs",
            "method": "POST",
            "payload": {"message": "Generate the morning report for today."},
            "cron_expr": "0 8 * * *",  # Every day at 8 AM
            "timezone": "UTC",
        },
        {
            "name": "hourly-weather-check",
            "description": "Check weather every hour",
            "endpoint": "/v1/agents/weather-checker/runs",
            "method": "POST",
            "payload": {"message": "What's the weather forecast?"},
            "cron_expr": "0 * * * *",  # Every hour
            "timezone": "UTC",
        },
    ]

    print("\nCreating schedules...")
    for schedule in schedules:
        try:
            response = httpx.post(
                f"{base_url}/v1/schedules",
                json=schedule,
                timeout=10.0,
            )
            if response.status_code == 201:
                data = response.json()
                print(
                    f"  Created: {data['name']} (next run: {data.get('next_run_at')})"
                )
            elif response.status_code == 400:
                # Schedule might already exist
                print(f"  Skipped: {schedule['name']} (already exists)")
            else:
                print(f"  Error creating {schedule['name']}: {response.text}")
        except Exception as e:
            print(f"  Error: {e}")


if __name__ == "__main__":
    print("Starting AgentOS with scheduled agents...")
    print("\nAvailable agents:")
    print("  - daily-reporter: Generates daily reports")
    print("  - weather-checker: Provides weather forecasts")

    # Note: In a real application, you would create schedules via API
    # after the server starts. This is shown for demonstration.
    print("\nServer starting on http://localhost:7777")
    print("Create schedules via: POST /v1/schedules")

    agent_os.run(port=7777)
