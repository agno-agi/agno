"""
Maxim Integration
=================

Demonstrates using Maxim to trace and log Agno agent and team calls.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.team.team import Team
from agno.tools.websearch import WebSearchTools
from agno.tools.yfinance import YFinanceTools

try:
    from maxim import Maxim
    from maxim.logger.agno import instrument_agno
except ImportError:
    raise ImportError(
        "`maxim` not installed. Please install using `uv pip install maxim-py`"
    )


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
# Instrument Agno with Maxim for automatic tracing and logging
instrument_agno(Maxim().logger())


# ---------------------------------------------------------------------------
# Create Agents And Team
# ---------------------------------------------------------------------------
# Web Search Agent: Fetches financial information from the web
web_search_agent = Agent(
    name="Web Agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[WebSearchTools()],
    instructions="Always include sources",
    markdown=True,
)

# Finance Agent: Gets financial data using YFinance tools
finance_agent = Agent(
    name="Finance Agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[YFinanceTools()],
    instructions="Use tables to display data",
    markdown=True,
)

# Aggregate both agents into a multi-agent system
multi_ai_team = Team(
    members=[web_search_agent, finance_agent],
    model=OpenAIChat(id="gpt-4o"),
    instructions="You are a helpful financial assistant. Answer user questions about stocks, companies, and financial data.",
    markdown=True,
)


# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("Welcome to the Financial Conversational Agent! Type 'exit' to quit.")
    messages = []
    while True:
        print("********************************")
        user_input = input("You: ")
        if user_input.strip().lower() in ["exit", "quit"]:
            print("Goodbye!")
            break
        messages.append({"role": "user", "content": user_input})
        conversation = "\n".join(
            [
                ("User: " + m["content"])
                if m["role"] == "user"
                else ("Agent: " + m["content"])
                for m in messages
            ]
        )
        response = multi_ai_team.run(
            f"Conversation so far:\n{conversation}\n\nRespond to the latest user message."
        )
        agent_reply = getattr(response, "content", response)
        print("---------------------------------")
        print("Agent:", agent_reply)
        messages.append({"role": "agent", "content": str(agent_reply)})
