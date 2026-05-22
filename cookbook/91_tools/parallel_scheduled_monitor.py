"""Parallel Scheduled Monitor — poll for events on a schedule.

This pattern works with AgentOS Scheduler:
1. Create a Parallel monitor (stores events on Parallel's side)
2. Schedule your agent to run periodically via AgentOS
3. Agent checks get_monitor_events on each run
4. Agent processes new events (send alerts, update CRM, etc.)

Setup:
    pip install parallel-web
    export PARALLEL_API_KEY=<your-api-key>

AgentOS Schedule Setup:
    POST /schedules
    {
        "name": "funding-monitor-check",
        "cron_expr": "0 * * * *",           # Every hour
        "endpoint": "/agents/my-agent/runs",
        "method": "POST",
        "payload": {"message": "Check for new funding announcements and alert me"}
    }
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.parallel import ParallelTools

# Agent that checks monitors and processes events
agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[
        ParallelTools(
            enable_monitor=True,
            enable_task=True,
        )
    ],
    markdown=True,
    instructions=[
        "You are a monitoring agent that runs on a schedule.",
        "When invoked, check all active monitors for new events.",
        "For each event found:",
        "  1. Summarize what changed",
        "  2. Assess if it's actionable",
        "  3. Report findings clearly",
        "If no new events, say 'No new events detected.'",
    ],
)

# Step 1: Create the monitor (run once to set up)
print("Step 1: Creating monitor...")
agent.print_response(
    "Create a monitor to track 'Series A funding announcements AI startups 2026' "
    "with 6-hour frequency. Save the monitor_id.",
    stream=True,
)

print("\n" + "=" * 60 + "\n")

# Step 2: Simulate scheduled run (this is what the scheduler would invoke)
print("Step 2: Checking for events (simulating scheduled run)...")
agent.print_response(
    "List my monitors, then check get_monitor_events for each active monitor. "
    "Report any new events found.",
    stream=True,
)


# In production with AgentOS, you would:
#
# 1. Deploy the agent to AgentOS
#
# 2. Create the monitor (one-time setup):
#    POST /agents/{agent_id}/runs
#    {"message": "Create a monitor for 'AI startup funding' with 6h frequency"}
#
# 3. Create a schedule to check events:
#    POST /schedules
#    {
#        "name": "ai-funding-monitor",
#        "cron_expr": "0 */2 * * *",  # Every 2 hours
#        "endpoint": "/agents/{agent_id}/runs",
#        "payload": {"message": "Check all monitors for new events"}
#    }
#
# 4. The scheduler invokes your agent every 2 hours
#    Agent calls list_monitors → get_monitor_events → processes results
