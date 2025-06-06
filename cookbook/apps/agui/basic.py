from agno.agent.agent import Agent
from agno.app.agui.app import AGUIApp
from agno.models.openai import OpenAIChat

chat_agent = Agent(
    name="Assistant",
    model=OpenAIChat(id="gpt-4o"),
    instructions="You are a helpful AI assistant.",
    add_datetime_to_instructions=True,
    markdown=True,
)

agui_app = AGUIApp(
    agent=chat_agent,
    name="Basic AG-UI Agent",
    app_id="basic_agui_agent",
    description="A basic agent that demonstrates AG-UI protocol integration.",
)

app = agui_app.get_app()

if __name__ == "__main__":
    agui_app.serve(app="basic:app", port=8000, reload=True)
