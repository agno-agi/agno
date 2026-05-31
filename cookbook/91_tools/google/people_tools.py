"""Google People Tools — Contact and directory lookups.

Setup:
1. Enable People API: https://console.cloud.google.com/apis/library/people.googleapis.com
2. Set env vars: GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_PROJECT_ID
3. For directory lookups, you need a Google Workspace account

Run: .venvs/demo/bin/python cookbook/91_tools/google/people_tools.py
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.google.people import GooglePeopleTools

# Basic agent with contact search
contact_agent = Agent(
    name="Contact Lookup",
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[GooglePeopleTools()],
    instructions="You help find contact information for people.",
    markdown=True,
)

if __name__ == "__main__":
    # Search personal contacts
    contact_agent.print_response(
        "Search my contacts for anyone named John", stream=True
    )

    # For Google Workspace users: search organization directory
    # contact_agent.print_response("Find Sarah from the marketing team in our company directory", stream=True)
