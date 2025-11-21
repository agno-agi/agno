from agents import get_sql_agent
from agno.playground import Playground, serve_playground_app

sql_agent = get_sql_agent(name="SQL Agent", model_id="openai:o4-mini")
reasoning_sql_agent = get_sql_agent(
    name="Reasoning SQL Agent", model_id="anthropic:claude-3-7-sonnet-latest"
)

app = Playground(agents=[sql_agent, reasoning_sql_agent]).get_app()

if __name__ == "__main__":
    serve_playground_app("playground:app", reload=True)
