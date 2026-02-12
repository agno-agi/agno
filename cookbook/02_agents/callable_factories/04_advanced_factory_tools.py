"""
Advanced Factory Tools
======================
Factory tools work with all agent and team features — connectable
toolkits that need setup, reasoning agents that plan before acting,
and teams that share tools across members.

This example shows a connectable database toolkit and a reasoning
agent, both using tools resolved from a callable factory.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run import RunContext
from agno.team import Team
from agno.tools import Toolkit

# ---------------------------------------------------------------------------
# Connectable Toolkit
# ---------------------------------------------------------------------------


class DatabaseToolkit(Toolkit):
    """Toolkit that connects to a database before use.

    When `_requires_connect` is True, the framework automatically
    calls `connect()` before the first tool invocation.
    """

    _requires_connect: bool = True

    def __init__(self):
        super().__init__(name="database_toolkit")
        self.connected = False
        self.register(self.query_database)

    def connect(self):
        self.connected = True
        print("--> DatabaseToolkit.connect() called")

    def query_database(self, query: str) -> str:
        """Query the database for information."""
        status = "connected" if self.connected else "NOT connected"
        return f"[DB {status}] Results for: {query}"


# ---------------------------------------------------------------------------
# Standalone tools
# ---------------------------------------------------------------------------


def search_web(query: str) -> str:
    """Search the web for information."""
    return f"Search results for: {query}"


def calculate(expression: str) -> str:
    """Evaluate a math expression."""
    try:
        result = eval(expression)  # noqa: S307
        return f"{expression} = {result}"
    except Exception as e:
        return f"Error: {e}"


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

db_toolkit = DatabaseToolkit()


def tools_for_role(run_context: RunContext):
    """Return different tools based on the user's role.

    - 'analyst' gets the database toolkit + calculator.
    - everyone else gets web search.
    """
    role = (run_context.session_state or {}).get("role", "viewer")
    print(f"--> Factory resolved tools for role: {role}")

    if role == "analyst":
        return [db_toolkit, calculate]
    return [search_web]


# ---------------------------------------------------------------------------
# Create Agent (with reasoning)
# ---------------------------------------------------------------------------

agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    reasoning=True,
    tools=tools_for_role,
    cache_callables=False,
    instructions=["Use the available tools to answer questions."],
)

# ---------------------------------------------------------------------------
# Create Team (with connectable toolkit)
# ---------------------------------------------------------------------------

helper = Agent(
    name="Helper",
    model=OpenAIChat(id="gpt-4o-mini"),
)

team = Team(
    name="AnalyticsTeam",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=tools_for_role,
    members=[helper],
    cache_callables=False,
    instructions=["Use the available tools to answer questions."],
)

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Reasoning agent with search tools
    print("=== Reasoning agent (viewer role) ===")
    agent.print_response(
        "Search for information about Python 3.12 new features",
        session_state={"role": "viewer"},
        stream=True,
    )

    # Reasoning agent with database + calculator
    print("\n=== Reasoning agent (analyst role) ===")
    agent.print_response(
        "What is 42 * 17 + 256?",
        session_state={"role": "analyst"},
        stream=True,
    )
    print(f"\n--> Toolkit connected: {db_toolkit.connected}")

    # Team with the same factory
    db_toolkit.connected = False
    print("\n=== Team (analyst role) ===")
    team.print_response(
        "Query the database for recent orders",
        session_state={"role": "analyst"},
        stream=True,
    )
    print(f"\n--> Toolkit connected: {db_toolkit.connected}")
