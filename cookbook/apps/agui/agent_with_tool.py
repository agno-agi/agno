from agno.agent.agent import Agent
from agno.app.agui.app import AGUIApp
from agno.models.openai import OpenAIChat
from agno.tools.yfinance import YFinanceTools

agent = Agent(
    tools=[
        YFinanceTools(
            stock_price=True, analyst_recommendations=True, stock_fundamentals=True
        )
    ],
    model=OpenAIChat(id="gpt-4o"),
    show_tool_calls=True,
    stream=True,
    stream_intermediate_steps=True,
    description="You are an investment analyst that researches stock prices, analyst recommendations, and stock fundamentals.",
    instructions="Format your response using markdown and use tables to display data where possible.",
)

agui_app = AGUIApp(
    agent=agent,
    name="Investment Analyst",
    app_id="investment_analyst",
    description="An investment analyst that researches stock prices, analyst recommendations, and stock fundamentals.",
)

app = agui_app.get_app()

if __name__ == "__main__":
    agui_app.serve(app="basic:app", port=8000, reload=True)
