"""
Dashscope Web Search
====================

Cookbook example for `dashscope/web_search.py`.

Qwen models on DashScope can search the web before answering. Set
`enable_search=True` to turn it on, and pass `search_options` to control
how the search runs (for example `forced_search` to always search).

Web search support depends on the model and the region of your DashScope
endpoint. See https://help.aliyun.com/zh/model-studio/web-search and set
`base_url` to your region's endpoint if needed.
"""

import asyncio

from agno.agent import Agent
from agno.models.dashscope import DashScope

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=DashScope(
        id="qwen-plus",
        enable_search=True,
        search_options={"forced_search": True, "search_strategy": "turbo"},
    ),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # --- Sync ---
    agent.print_response("What are the top AI news stories today?")

    # --- Sync + Streaming ---
    agent.print_response("What is the weather in Hangzhou today?", stream=True)

    # --- Async + Streaming ---
    asyncio.run(
        agent.aprint_response("What is the latest Qwen model release?", stream=True)
    )
