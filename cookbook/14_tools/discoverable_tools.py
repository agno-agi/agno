import json

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools import DiscoverableTools


def send_email(to: str, subject: str, body: str) -> str:
    """Email a recipient.

    Args:
        to: Email address of the recipient
        subject: Subject line of the email
        body: Body content of the email

    Returns:
        Confirmation message
    """
    return json.dumps({"status": "sent", "to": to, "subject": subject})


def search_contacts(query: str) -> str:
    """Search for contacts by name or email.

    Args:
        query: Search query to find contacts

    Returns:
        List of matching contacts
    """
    return json.dumps({"contacts": [{"name": "John Doe", "email": "john@example.com"}]})


def schedule_meeting(title: str, attendees: list[str], date: str, time: str) -> str:
    """Schedule a meeting with attendees.

    Args:
        title: Title of the meeting
        attendees: List of attendee email addresses
        date: Date of the meeting (YYYY-MM-DD)
        time: Time of the meeting (HH:MM)

    Returns:
        Meeting confirmation details
    """
    return json.dumps({"meeting_id": "mtg_123", "title": title, "scheduled": True})


def get_weather(city: str) -> str:
    """Get the current weather for a city.

    Args:
        city: Name of the city

    Returns:
        Weather information
    """
    return json.dumps({"city": city, "temperature": 72, "condition": "sunny"})


def calculate_expense(amount: float, category: str, description: str) -> str:
    """Log an expense for tracking.

    Args:
        amount: Amount of the expense
        category: Category of the expense (e.g., travel, food, supplies)
        description: Description of the expense

    Returns:
        Expense record confirmation
    """
    return json.dumps({"expense_id": "exp_456", "amount": amount, "category": category})


# Create DiscoverableTools with the tools the agent can discover and use
discoverable_tools = DiscoverableTools(
    discoverable_tools=[
        send_email,
        search_contacts,
        schedule_meeting,
        get_weather,
        calculate_expense,
    ]
)

# Create an agent with tool search capability
# The agent will have 3 tools: search_tools, list_all_tools, and use_tool
# It can discover and execute any of the 5 discoverable tools dynamically
basic_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[discoverable_tools],
    instructions=[
        "You Are a very helpful assistant. You perform tasks that are asked by the user",
    ],
    markdown=True,
)

if __name__ == "__main__":
    basic_agent.print_response("What is the weather in London?")
