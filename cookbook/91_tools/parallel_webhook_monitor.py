"""Parallel Webhook Monitor — real-time event-driven agent invocation.

This pattern uses webhooks for instant notification:
1. Create AgentOS with enable_webhooks=True
2. Create a Parallel monitor with webhook_url pointing to your agent
3. When Parallel detects events, it POSTs to your webhook
4. AgentOS invokes your agent with the payload
5. Agent uses get_monitor_events to fetch full details

Setup:
    pip install parallel-web
    export PARALLEL_API_KEY=<your-api-key>

Deploy:
    # Your AgentOS must be publicly accessible (ngrok, cloudflare tunnel, etc.)
    ngrok http 8000
    # Use the ngrok URL as your webhook base
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.os.app import AgentOS
from agno.tools.parallel import ParallelTools

# Agent that processes webhook events
monitor_agent = Agent(
    agent_id="funding-monitor",
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[ParallelTools(enable_monitor=True, enable_task=True)],
    markdown=True,
    instructions=[
        "You are a funding announcement monitor.",
        "When you receive a webhook event:",
        "  1. Extract the monitor_id from the payload",
        "  2. Call get_monitor_events to fetch full event details",
        "  3. Summarize each funding announcement found",
        "  4. Highlight the company name, amount raised, and investors",
    ],
)

# AgentOS with webhooks enabled
app = AgentOS(
    agents=[monitor_agent],
    enable_webhooks=True,
)


# After deploying, create the monitor pointing to your webhook:
#
# from parallel import Parallel
#
# client = Parallel()
# monitor = client.monitors.create(
#     query="Series A funding announcements AI startups",
#     frequency="6h",
#     webhook={
#         "url": "https://your-ngrok-url.ngrok.io/webhooks/funding-monitor",
#         "events": ["monitor.event.detected"],
#     },
# )
# print(f"Monitor created: {monitor.id}")
#
# When Parallel detects a funding announcement:
# 1. Parallel POSTs to /webhooks/funding-monitor
# 2. AgentOS invokes funding-monitor agent with the payload
# 3. Agent calls get_monitor_events(monitor_id) to get details
# 4. Agent processes and returns summary


if __name__ == "__main__":
    import uvicorn

    print("Starting AgentOS with webhooks enabled...")
    print("Webhook endpoint: POST /webhooks/funding-monitor")
    print()
    print("To test locally:")
    print("  1. Start ngrok: ngrok http 8000")
    print("  2. Create a Parallel monitor with webhook_url pointing to ngrok URL")
    print("  3. Wait for events or use trigger_monitor to force a check")

    uvicorn.run(app.get_app(), host="0.0.0.0", port=8000)
