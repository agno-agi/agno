"""
Send a Proactive Alert to a Teams User
======================================

Once a user has chatted with the bot at least once, the interface stores a
conversation reference in that user's latest session. Any code — a scheduled
job, a webhook handler, another agent's tool — can then call
`teams.asend_alert(user_id, text)` (or the sync `teams.send_alert(...)`
wrapper) to push a message into Teams without an inbound trigger.

This example runs the bot server AND schedules a one-off alert 30 seconds
after startup, so you can watch the flow end-to-end:

  1. Start this file
  2. Message the bot at least once in Teams (any text)  → conversation ref saved
  3. Wait for the scheduled alert to fire               → proactive message

Run: .venvs/demo/bin/python cookbook/05_agent_os/20_teams/proactive_alert.py
"""

import asyncio
import os
import threading

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.interfaces.teams import MicrosoftTeams

# ---------------------------------------------------------------------------
# Build the bot as usual
# ---------------------------------------------------------------------------

db = SqliteDb(
    id="teams-alerts-db",
    db_file="tmp/teams_alerts.db",
)

assistant = Agent(
    id="teams-alerts-agent",
    name="Alerts Assistant",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    add_history_to_context=True,
    instructions=[
        "You are a background monitor that also chats with users.",
        "Keep replies short.",
    ],
)

teams = MicrosoftTeams(agent=assistant)

agent_os = AgentOS(
    id="teams-alerts-os",
    description="AgentOS that also emits scheduled proactive alerts to Teams.",
    agents=[assistant],
    interfaces=[teams],
)
app = agent_os.get_app()


def _demo_alert_worker():
    target_user_id = os.getenv("ALERT_USER_ID")  # aadObjectId or channel-scoped from.id
    if not target_user_id:
        print(
            "[demo] ALERT_USER_ID not set — skipping proactive demo. "
            "Message the bot once, read the from.id, then export ALERT_USER_ID and restart."
        )
        return

    async def _loop():
        print(f"[demo] scheduling proactive alert to {target_user_id} in 30s")
        await asyncio.sleep(30)
        while True:
            sent = await teams.asend_alert(
                user_id=target_user_id,
                text="**Demo alert** from the Teams cookbook — this arrived without you asking.",
            )
            if sent:
                print(f"[demo] Proactive alert delivered to {target_user_id}")
                return
            print(
                f"[demo] No conversation reference yet for {target_user_id}; retrying in 15s."
            )
            await asyncio.sleep(15)

    asyncio.run(_loop())


threading.Thread(target=_demo_alert_worker, daemon=True).start()


# ---------------------------------------------------------------------------
# Run the Teams Server
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app)
