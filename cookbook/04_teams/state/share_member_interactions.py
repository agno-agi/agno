from agno.agent.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.team.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools

db = SqliteDb(db_file="tmp/agents.db")

web_research_agent = Agent(
    name="Web Research Agent",
    model=OpenAIChat(id="o3-mini"),
    tools=[DuckDuckGoTools()],
    instructions="You are a web research agent that can answer questions from the web.",
)

report_agent = Agent(
    name="Report Agent",
    model=OpenAIChat(id="o3-mini"),
    instructions="You are a report agent that can write a report from the web research.",
)

team = Team(
    model=OpenAIChat(id="o3-mini"),
    db=db,
    members=[web_research_agent, report_agent],
    share_member_interactions=True,
    instructions=[
        "You are a team of agents that can research the web and write a report.",
        "First, research the web for information about the topic.",
        "Then, use your report agent to write a report from the web research.",
    ],
    show_members_responses=True,
    debug_mode=True,
)

team.print_response("How are LEDs made?")
