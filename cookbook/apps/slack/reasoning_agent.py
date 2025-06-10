from agno.agent import Agent
from agno.app.slack.app import SlackAPI
from agno.models.anthropic.claude import Claude
from agno.tools.thinking import ThinkingTools
from agno.tools.yfinance import YFinanceTools

reasoning_finance_agent = Agent(
    name="Reasoning Finance Agent",
    model=Claude(id="claude-3-7-sonnet-latest"),
    tools=[
        ThinkingTools(add_instructions=True),
        YFinanceTools(
            stock_price=True,
            analyst_recommendations=True,
            company_info=True,
            company_news=True,
        ),
    ],
    instructions="Use tables to display data. When you use thinking tools, keep the thinking brief.",
    add_datetime_to_instructions=True,
    markdown=True,
)

slack_api_app = SlackAPI(
    agent=reasoning_finance_agent,
    name="Reasoning Finance Agent",
    app_id="reasoning_finance_agent",
    description="A agent that can reason about finance and stock prices.",
)
app = slack_api_app.get_app()

if __name__ == "__main__":
    slack_api_app.serve("reasoning_agent:app", port=8000, reload=True)
