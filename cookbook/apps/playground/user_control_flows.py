"""🤝 Human-in-the-Loop: Allowing users to provide input externally

This example shows how to use the UserControlFlowTools to allow the agent to get user input dynamically.
If the agent doesn't have enough information to complete a task, it will use the toolkit to get the information it needs from the user.
"""

import json

import httpx
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.playground import Playground
from agno.storage.postgres import PostgresStorage
from agno.tools import tool
from agno.tools.toolkit import Toolkit
from agno.tools.user_control_flow import UserControlFlowTools
from agno.tools.wikipedia import WikipediaTools
from agno.tools.yfinance import YFinanceTools

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"


@tool(requires_confirmation=True)
def get_top_hackernews_stories(num_stories: int) -> str:
    """Fetch top stories from Hacker News.

    Args:
        num_stories (int): Number of stories to retrieve

    Returns:
        str: JSON string containing story details
    """
    # Fetch top story IDs
    response = httpx.get("https://hacker-news.firebaseio.com/v0/topstories.json")
    story_ids = response.json()

    # Yield story details
    all_stories = []
    for story_id in story_ids[:num_stories]:
        story_response = httpx.get(
            f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json"
        )
        story = story_response.json()
        if "text" in story:
            story.pop("text", None)
        all_stories.append(story)
    return json.dumps(all_stories)


@tool(requires_user_input=True, user_input_fields=["to_address"])
def send_email(subject: str, body: str, to_address: str) -> str:
    """
    Send an email.

    Args:
        subject (str): The subject of the email.
        body (str): The body of the email.
        to_address (str): The address to send the email to.
    """
    return f"Sent email to {to_address} with subject {subject} and body {body}"


class EmailTools(Toolkit):
    def __init__(self, *args, **kwargs):
        super().__init__(
            name="EmailTools", tools=[self.send_email, self.get_emails], *args, **kwargs
        )

    def send_email(self, subject: str, body: str, to_address: str) -> str:
        """Send an email to the given address with the given subject and body.

        Args:
            subject (str): The subject of the email.
            body (str): The body of the email.
            to_address (str): The address to send the email to.
        """
        return f"Sent email to {to_address} with subject {subject} and body {body}"

    def get_emails(self, date_from: str, date_to: str) -> str:
        """Get all emails between the given dates.

        Args:
            date_from (str): The start date (in YYYY-MM-DD format).
            date_to (str): The end date (in YYYY-MM-DD format).
        """
        return [
            {
                "subject": "Hello",
                "body": "Hello, world!",
                "to_address": "test@test.com",
                "date": date_from,
            },
            {
                "subject": "Random other email",
                "body": "This is a random other email",
                "to_address": "john@doe.com",
                "date": date_to,
            },
        ]


double_confirmation_agent = Agent(
    agent_id="double-confirmation-agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[
        get_top_hackernews_stories,
        WikipediaTools(requires_confirmation_tools=["search_wikipedia"]),
    ],
    markdown=True,
    storage=PostgresStorage(
        table_name="hitl_sessions", db_url=db_url, auto_upgrade_schema=True
    ),
)
user_input_required_agent = Agent(
    agent_id="user-input-required-agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[send_email],
    markdown=True,
    storage=PostgresStorage(
        table_name="hitl_sessions", db_url=db_url, auto_upgrade_schema=True
    ),
)
agentic_user_input_agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    agent_id="agentic-user-input-agent",
    tools=[EmailTools(), UserControlFlowTools()],
    markdown=True,
    storage=PostgresStorage(
        table_name="hitl_sessions", db_url=db_url, auto_upgrade_schema=True
    ),
)

confirmation_required_agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    agent_id="confirmation-required-agent",
    tools=[
        get_top_hackernews_stories,
        YFinanceTools(requires_confirmation_tools=["get_current_stock_price"]),
    ],
    markdown=True,
    storage=PostgresStorage(
        table_name="hitl_sessions", db_url=db_url, auto_upgrade_schema=True
    ),
)
combined_agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    agent_id="combined-agent",
    tools=[
        EmailTools(),
        UserControlFlowTools(),
        send_email,
        get_top_hackernews_stories,
    ],
    markdown=True,
    storage=PostgresStorage(
        table_name="hitl_sessions", db_url=db_url, auto_upgrade_schema=True
    ),
)

playground = Playground(
    agents=[
        agentic_user_input_agent,
        confirmation_required_agent,
        user_input_required_agent,
        combined_agent,
        double_confirmation_agent,
    ],
    app_id="hitl-playground-app",
    name="HITL Playground",
    description="A playground for HITL",
)

app = playground.get_app()

if __name__ == "__main__":
    playground.serve(app="user_control_flows:app", reload=True)


# Send an email with the body 'What is the weather in Tokyo?
# Fetch the top 2 hackernews stories.
# Send an email with the subject 'Hello' and the body 'Hello, world!
