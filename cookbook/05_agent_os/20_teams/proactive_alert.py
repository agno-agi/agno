"""
Send a Proactive Alert to a Teams User
======================================

Push a message into Teams without an inbound trigger, using the conversation
reference stored on the user's session by their first message. Call
`teams.asend_alert(user_id, text)` from a coroutine, or `teams.send_alert(...)`
from a script. This example serves the bot and schedules one alert after 30s:

  1. Start this file
  2. Message the bot at least once in Teams  → conversation ref saved
  3. Wait for the scheduled alert to fire    → proactive message

Prerequisites: ALERT_USER_ID (see README.md), plus the credentials basic.py needs
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
# Create the Teams AgentOS
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


# ---------------------------------------------------------------------------
# Run the Teams Server
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Started here, not at import: `app` above is the ASGI entry point, so an
    # `uvicorn proactive_alert:app` or a reload worker would otherwise spawn the
    # demo loop as a side effect of importing the module.
    threading.Thread(target=_demo_alert_worker, daemon=True).start()
    agent_os.serve(app=app)
