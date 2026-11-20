"""
Feishu / Lark Tools
===================

Environment variables:
    FEISHU_APP_ID        App ID from the Feishu Open Platform (https://open.feishu.cn/app)
    FEISHU_APP_SECRET    App Secret of the same app
    FEISHU_BASE_URL      Optional. Set to https://open.larksuite.com for Lark (international).

The app needs these permissions (scopes) enabled and published:
    im:message, im:message:send_as_bot, im:chat, contact:user.base:readonly

The bot must be added to a group before it can send messages there.
Get a chat_id: list chats with the agent, or open the group settings in Feishu.
"""

from agno.agent import Agent
from agno.tools.feishu import FeishuTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

# Example 1: Default tools (send_message, get_chat, list_chats, get_user)
agent = Agent(
    tools=[FeishuTools()],
    markdown=True,
)

# Example 2: All tools, including reply_message and delete_message
agent_all = Agent(
    tools=[FeishuTools(all=True)],
    markdown=True,
)

# Example 3: Send-only bot that must confirm before deleting anything
agent_send_only = Agent(
    tools=[
        FeishuTools(
            enable_get_chat=False,
            enable_list_chats=False,
            enable_get_user=False,
            enable_delete_message=True,
            requires_confirmation_tools=["delete_message"],
        )
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response(
        "List the chats I'm in, then send 'Hello from Agno!' to the first one",
        stream=True,
    )

    # agent_all.print_response(
    #     "Send 'Test message' to chat oc_xxx, then delete it",
    #     stream=True,
    # )
