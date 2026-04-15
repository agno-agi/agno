"""Slack HITL Approval Demo

An agent with a tool that requires user confirmation before executing.
When the agent calls the tool, Slack shows Approve/Reject buttons.
The agent only proceeds after the user clicks Approve.

Setup:
1. Set env vars: SLACK_TOKEN, SLACK_SIGNING_SECRET, OPENAI_API_KEY
2. Configure Slack app with:
   - Event Subscriptions: <your_url>/slack/events
   - Interactivity Request URL: <your_url>/slack/interactions
   - Bot scopes: app_mentions:read, assistant:write, chat:write, im:history, im:read, im:write
3. Run: .venvs/demo/bin/python cookbook/05_agent_os/interfaces/slack/hitl_approval.py
4. Start ngrok: ngrok http 7778
5. DM the bot: "send an email to alice@example.com saying hello"
6. Bot will show an approval card with Approve/Reject buttons
"""

from agno.agent import Agent
from agno.approval import approval
from agno.models.openai import OpenAIChat
from agno.os.app import AgentOS
from agno.os.interfaces.slack import Slack
from agno.tools import tool


@approval
@tool(
    description="Send an email to the specified recipient. This is an irreversible action."
)
def send_email(to: str, subject: str, body: str) -> str:
    return f"Email sent to {to} with subject '{subject}'"


@tool(description="Draft an email without sending it.")
def draft_email(to: str, subject: str, body: str) -> str:
    return f"Draft created for {to}: subject='{subject}', body='{body[:50]}...'"


agent = Agent(
    name="Email Assistant",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[send_email, draft_email],
    instructions=[
        "You are an email assistant.",
        "When asked to send an email, use the send_email tool.",
        "When asked to draft, use the draft_email tool.",
    ],
    tool_call_limit=5,
)

agent_os = AgentOS(
    agents=[agent],
    interfaces=[
        Slack(
            agent=agent,
            reply_to_mentions_only=False,
        ),
    ],
)
app = agent_os.get_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=7777)
