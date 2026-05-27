"""
Discoverable Tools - Token Savings Validation
=============================================

Instruments Model._format_tools to print the exact tool list sent to the
provider on each API iteration. Proves that:

  1. Discoverable tools are NOT preloaded into the first API call
  2. Only matched tools are injected after search_tools runs
  3. Unmatched tools NEVER enter context

Use this script to validate the token-savings thesis when reviewing the
DiscoverableTools implementation.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools import DiscoverableTools


# ---------------------------------------------------------------------------
# Instrument _format_tools via a subclass to log per-iteration tool dispatch
# ---------------------------------------------------------------------------
class InstrumentedOpenAIResponses(OpenAIResponses):
    _call_idx: int = 0

    def _format_tools(self, tools):
        result = super()._format_tools(tools)
        self._call_idx += 1
        names = [t["function"]["name"] for t in result if t.get("type") == "function"]
        print(f">>> API CALL #{self._call_idx}: {len(result)} tools sent -> {names}")
        return result


# ---------------------------------------------------------------------------
# Tools - 1 always-visible, 7 discoverable
# ---------------------------------------------------------------------------
def get_weather(city: str) -> str:
    """Get current weather for a city."""
    return f"Weather in {city}: 22C, sunny"


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
    model=InstrumentedOpenAIResponses(id="gpt-5.4"),
    tools=[get_weather, discoverable],
    instructions=[
        "You MUST use tools to perform actions, never just describe them.",
        "When a capability is missing from your visible tools, call search_tools(query) FIRST.",
        "After search_tools returns, immediately call the discovered tool with proper arguments.",
    ],
)


if __name__ == "__main__":
    print("=== POOL: 7 discoverable tools | ALWAYS-VISIBLE: 1 (get_weather) ===\n")
    agent.run("Find Jordan in contacts then send Jordan an email saying hello.")
    print(
        "\n=== Expected: API CALL #1 has 2 tools (get_weather + search_tools), "
        "subsequent calls grow only with what was discovered ==="
    )
