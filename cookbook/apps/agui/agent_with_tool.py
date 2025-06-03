from agno.agent.agent import Agent
from agno.app.agui.app import AGUIApp
from agno.models.openai import OpenAIChat
from agno.tools.calculator import CalculatorTools

calculator_agent = Agent(
    name="Calculator Agent",
    model=OpenAIChat(id="gpt-4o"),
    instructions="You are a helpful AI assistant focused on using tools to perform arithmetic calculations.",
    tools=[CalculatorTools()],
    show_tool_calls=True,
    add_datetime_to_instructions=True,
    markdown=True,
)

agui_app = AGUIApp(
    agent=calculator_agent,
    name="Calculator Agent",
    app_id="calculator_agent",
    description="An Agent with toolsthat demonstrates AG-UI protocol integration.",
)

app = agui_app.get_app()

if __name__ == "__main__":
    agui_app.serve(app="basic:app", port=8000, reload=True)
