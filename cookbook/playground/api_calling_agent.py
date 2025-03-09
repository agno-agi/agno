from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.playground import Playground, serve_playground_app
from agno.storage.agent.sqlite import SqliteAgentStorage
from agno.tools.api import ApiTools

agent_storage: str = "tmp/agents.db"

api_agent = Agent(
    name="API Agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[ApiTools(base_url="https://dog.ceo/api", make_request=True)],
    instructions=["Always display only the response.data of the API request"],
    storage=SqliteAgentStorage(table_name="api_calling_agent", db_file=agent_storage),
    add_datetime_to_instructions=True,
    add_history_to_messages=True,
    num_history_responses=5,
    markdown=True,
)

app = Playground(agents=[api_agent]).get_app()

if __name__ == "__main__":
    serve_playground_app("api_calling_agent:app", reload=True)
