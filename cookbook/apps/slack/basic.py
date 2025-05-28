from agno.agent import Agent
from agno.app.slack.app import SlackAPI
from agno.models.openai import OpenAIChat

basic_agent = Agent(
    name="Basic Agent",
    model=OpenAIChat(id="gpt-4o"),
    add_history_to_messages=True,
    num_history_responses=3,
    add_datetime_to_instructions=True,
)

slack_api_app = SlackAPI(
    agent=basic_agent,
)
app = slack_api_app.get_app()

if __name__ == "__main__":
    slack_api_app.serve("basic:app", port=8000, reload=True)
