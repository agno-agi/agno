"""
This example shows how to use Maxim to log agent calls and traces.

Steps to get started with Maxim:
1. Install Maxim: pip install maxim-py
2. Add instrument_agno(Maxim().logger()) to initialize tracing
3. Authentication:
 - Go to https://getmaxim.ai and create an account
 - Generate your API key from the settings
 - Export your API key as an environment variable:
    - export MAXIM_API_KEY=<your-api-key>
    - export MAXIM_LOG_REPO_ID=<your-repo-id>
4. All agent interactions will be automatically traced and logged to Maxim
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.team.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.yfinance import YFinanceTools

try:
    from maxim import Maxim
    from maxim.logger.agno import instrument_agno
except ImportError:
    raise ImportError(
        "`maxim` not installed. Please install using `pip install maxim-py`"
    )

# Instrument Agno with Maxim for automatic tracing and logging
instrument_agno(Maxim().logger())

# Web Search Agent: Fetches financial information from the web
web_search_agent = Agent(
    name="Web Agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[DuckDuckGoTools()],
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
