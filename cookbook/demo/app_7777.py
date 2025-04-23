from agents.agno_assist import agno_assist
from agents.basic import (
    finance_agent,
    image_agent,
    research_agent,
    simple_agent,
    web_agent,
    youtube_agent,
)
from agents.memory_agent import get_memory_agent
from agno.playground import Playground, serve_playground_app
from sql.agents import get_sql_agent
from teams.reasoning_finance_team import get_reasoning_finance_team

sql_agent = get_sql_agent(name="SQL Agent", model_id="openai:o4-mini")
reasoning_sql_agent = get_sql_agent(
    name="Reasoning SQL Agent",
    model_id="anthropic:claude-3-7-sonnet-latest",
    reasoning=True,
)
memory_agent = get_memory_agent()
reasoning_finance_team = get_reasoning_finance_team()

app = Playground(
    agents=[
        sql_agent,
        reasoning_sql_agent,
        agno_assist,
        memory_agent,
        simple_agent,
        web_agent,
        finance_agent,
        youtube_agent,
        research_agent,
        image_agent,
    ],
    teams=[reasoning_finance_team],
).get_app()

if __name__ == "__main__":
    serve_playground_app("app_7777:app", port=7777)
