from agno.agent import Agent
from agno.app.serve import serve_app
from agno.app.slack.app import SlackAPI
from agno.models.openai import OpenAIChat

basic_agent = Agent(
    name="Basic Agent",
    model=OpenAIChat(id="gpt-4o"),
    add_history_to_messages=True,
    num_history_responses=3,
    add_datetime_to_instructions=True,
)

app = SlackAPI(
    agent=basic_agent,
).get_app()

if __name__ == "__main__":
    serve_app("basic:app", port=8000, reload=True)
