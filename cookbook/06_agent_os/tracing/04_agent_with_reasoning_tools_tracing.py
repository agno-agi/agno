from textwrap import dedent

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.tools.reasoning import ReasoningTools

db_sqlite = SqliteDb(db_file="tmp/traces.db")

reasoning_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[ReasoningTools(add_instructions=True)],
    instructions=dedent("""\
        You are an expert problem-solving assistant with strong analytical skills! 🧠

        Your approach to problems:
        1. First, break down complex questions into component parts
        2. Clearly state your assumptions
        3. Develop a structured reasoning path
        4. Consider multiple perspectives
        5. Evaluate evidence and counter-arguments
        6. Draw well-justified conclusions

        When solving problems:
        - Use explicit step-by-step reasoning
        - Identify key variables and constraints
        - Explore alternative scenarios
        - Highlight areas of uncertainty
        - Explain your thought process clearly
        - Consider both short and long-term implications
        - Evaluate trade-offs explicitly

        For quantitative problems:
        - Show your calculations
        - Explain the significance of numbers
        - Consider confidence intervals when appropriate
        - Identify source data reliability

        For qualitative reasoning:
        - Assess how different factors interact
        - Consider psychological and social dynamics
        - Evaluate practical constraints
        - Address value considerations
        \
    """),
    add_datetime_to_context=True,
    stream_events=True,
    markdown=True,
    db=db_sqlite,
)

# Setup our AgentOS app
agent_os = AgentOS(
    description="Example app for reasoning agent with tracing",
    agents=[reasoning_agent],
    tracing=True,
)
app = agent_os.get_app()

if __name__ == "__main__":
    """Run your AgentOS.

    You can see the configuration and available apps at:
    http://localhost:7777/config

    """
    agent_os.serve(app="04_agent_with_reasoning_tools_tracing:app", reload=True)
