"""
Discoverable Tools
==================

Demonstrates DiscoverableTools: a pool of tools withheld from the model's
context until discovered via a search_tools meta-tool. Discovered tools then
become regular callable Functions on subsequent turns.

Use case: large tool catalogs (10+ tools) where loading every schema upfront
wastes context tokens. Inspired by Anthropic's tool_search pattern but
model-agnostic — works with any provider.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools import DiscoverableTools


def get_weather(city: str) -> str:
    """Get current weather for a city."""
    return f"Weather in {city}: 22°C, sunny"


def get_stock_price(ticker: str) -> str:
    """Get latest stock price for a ticker symbol."""
    return f"{ticker}: $142.50"


def send_email(to: str, subject: str, body: str) -> str:
    """Email a recipient with subject and body."""
    return f"Email sent to {to} (subject={subject!r}, body_len={len(body)})"


def search_contacts(query: str) -> str:
    """Search address book for contacts matching a query."""
    return f"Found 3 contacts matching: {query}"


def list_calendar_events(date: str) -> str:
    """List calendar events on a given date (YYYY-MM-DD)."""
    return f"Events on {date}: standup 10am, review 2pm"


def create_jira_ticket(title: str, description: str) -> str:
    """Create a new Jira ticket."""
    return f"Created JIRA-1234: {title} ({len(description)} char description)"


def query_database(sql: str) -> str:
    """Run a read-only SQL query against the analytics database."""
    return f"Returned 42 rows for query: {sql[:30]}..."


def translate_text(text: str, target_language: str) -> str:
    """Translate text to the target language."""
    return f"Translated {len(text)} chars to {target_language}"


# ---------------------------------------------------------------------------
# Build agent with discoverable tools
# ---------------------------------------------------------------------------
# Only `get_weather` is always visible. The other 7 tools are discoverable —
# the agent must call search_tools(query) to find and activate them.
discoverable = DiscoverableTools(
    tools=[
        get_stock_price,
        send_email,
        search_contacts,
        list_calendar_events,
        create_jira_ticket,
        query_database,
        translate_text,
    ],
    max_results=3,
)

agent = Agent(
    name="Productivity Assistant",
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[get_weather, discoverable],
    instructions=[
        "You MUST use tools to perform actions, never just describe them.",
        "When a capability is missing from your visible tools, call search_tools(query) FIRST.",
        "After search_tools returns, immediately call the discovered tool with proper arguments.",
    ],
    markdown=True,
)


if __name__ == "__main__":
    # Expected flow:
    #   1. search_tools("contacts email") -> injects search_contacts + send_email
    #   2. search_contacts("Jordan") -> returns matching contacts
    #   3. send_email(to=..., subject=..., body=...) -> sends
    agent.print_response(
        "Find Jordan in contacts then send Jordan an email saying hello."
    )
