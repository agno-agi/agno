"""
Basic Lark (Feishu) Agent
=========================

Minimal Lark bot that responds to messages in private chats and when mentioned
in groups. Uses SQLite for session persistence so the agent remembers
conversation history across restarts.

Key concepts:
  - ``reply_to_mentions_only=True`` ignores regular group messages and only
    responds when the bot is @mentioned.
  - ``streaming=True`` sends an interactive card and PATCHes it in place as
    tokens arrive, so the user sees incremental output.
  - ``add_history_to_context=True`` feeds the last N runs back into the prompt.

Setup:
  1. Create a custom app at https://open.feishu.cn/app and enable the Bot ability.
  2. Subscribe to the ``im.message.receive_v1`` event.
  3. Grant permissions: ``im:message``, ``im:message:send_as_bot``,
     ``im:message:receive_as_bot``, ``im:message:update``.
  4. Set the env vars below.
  5. Expose the server publicly (e.g. via ngrok) and set the webhook URL to
     ``https://<your-host>/lark/webhook`` in the Feishu console.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.deepseek import DeepSeek
from agno.os.app import AgentOS
from agno.os.interfaces.lark import Lark

agent_db = SqliteDb(session_table="lark_sessions", db_file="tmp/lark_basic.db")

lark_agent = Agent(
    name="Lark Bot",
    model=DeepSeek(id="deepseek-v4-flash"),
    db=agent_db,
    instructions=[
        "You are a helpful assistant on Lark (Feishu).",
        "Keep responses concise and friendly.",
        "When in a group, you respond only when mentioned with @.",
    ],
    add_history_to_context=True,
    num_history_runs=3,
    add_datetime_to_context=True,
    markdown=True,
)

agent_os = AgentOS(
    agents=[lark_agent],
    interfaces=[
        Lark(
            agent=lark_agent,
            reply_to_mentions_only=True,
            streaming=True,
        )
    ],
)
app = agent_os.get_app()

if __name__ == "__main__":
    """Run your AgentOS.

    You can see the configuration and available apps at:
    http://localhost:7777/config

    """
    agent_os.serve(app="basic:app", reload=True)
