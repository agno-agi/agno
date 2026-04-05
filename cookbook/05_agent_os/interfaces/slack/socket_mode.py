"""
Slack Socket Mode Agent
=======================

Runs a Slack bot using Socket Mode instead of the default HTTP webhook transport.
Socket Mode connects outbound to Slack over a WebSocket, so no public URL or
reverse proxy is needed.  This is ideal for local development and internal
deployments behind a firewall.

Key differences from the HTTP mode (basic.py):
  - ``socket_mode=True`` — enables the WebSocket transport
  - ``app_token`` — App-Level Token (``xapp-...``) for the WebSocket handshake
  - ``slack.start()`` — blocks until stopped (no FastAPI / uvicorn needed)

Setup:
  1. In your Slack app settings, go to Settings → Socket Mode and enable it.
  2. Generate an App-Level Token with the ``connections:write`` scope and copy it.
  3. Set environment variables::

       export SLACK_TOKEN=xoxb-...
       export SLACK_APP_TOKEN=xapp-...

  4. Run the script::

       .venvs/demo/bin/python cookbook/05_agent_os/interfaces/slack/socket_mode.py

Slack scopes: app_mentions:read, assistant:write, chat:write, im:history
"""

from agno.agent import Agent
from agno.db.sqlite.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.os.interfaces.slack import Slack

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------

agent_db = SqliteDb(session_table="agent_sessions", db_file="tmp/persistent_memory.db")

agent = Agent(
    name="Socket Mode Agent",
    model=OpenAIChat(id="gpt-4o"),
    db=agent_db,
    add_history_to_context=True,
    num_history_runs=3,
    add_datetime_to_context=True,
    instructions="You are a helpful assistant running in a Slack workspace.",
)

slack = Slack(
    agent=agent,
    reply_to_mentions_only=True,
    socket_mode=True,
    # app_token can be passed here or read from SLACK_APP_TOKEN env var
    # app_token="xapp-...",
)

# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Blocks until stopped (Ctrl-C). No web server required.
    slack.start()
