"""
Route Mode with Fallback Agent

Demonstrates routing with a general-purpose fallback agent that handles
requests when no specialist is a clear match.

"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.team.mode import TeamMode
from agno.team.team import Team

# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------

sql_agent = Agent(
    name="SQL Expert",
    role="Writes and optimizes SQL queries",
    model=OpenAIResponses(id="gpt-5.2"),
    instructions=[
        "You are an SQL expert.",
        "Write correct, optimized SQL queries.",
        "Explain query plans and indexing strategies when asked.",
    ],
)

python_agent = Agent(
    name="Python Expert",
    role="Writes Python code and solves Python-specific problems",
    model=OpenAIResponses(id="gpt-5.2"),
    instructions=[
        "You are a Python expert.",
        "Write idiomatic, well-structured Python code.",
        "Follow PEP 8 and use type hints.",
    ],
)

general_agent = Agent(
    name="General Assistant",
    role="Handles general questions that do not match a specialist",
    model=OpenAIResponses(id="gpt-5.2"),
    instructions=[
        "You are a helpful general assistant.",
        "Answer questions clearly and concisely.",
        "If the question is about SQL or Python, still do your best.",
    ],
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------

team = Team(
    name="Dev Help Router",
    mode=TeamMode.route,
    model=OpenAIResponses(id="gpt-5.2"),
    members=[sql_agent, python_agent, general_agent],
    instructions=[
        "You route questions to the right expert.",
        "- SQL or database questions -> SQL Expert",
        "- Python questions -> Python Expert",
        "- Everything else -> General Assistant",
        "When in doubt, route to the General Assistant.",
    ],
    show_members_responses=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # SQL question
    team.print_response(
        "Write a query to find the top 10 customers by total order value, "
        "joining the customers and orders tables.",
        stream=True,
    )

    print("\n" + "=" * 60 + "\n")

    # General question (fallback)
    team.print_response(
        "What are some good practices for code review?",
        stream=True,
    )
