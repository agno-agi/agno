from textwrap import dedent

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.models.google import Gemini
from ..personal_assistant_team.knowledge_agent import knowledge_agent
from agno.team.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.github import GithubTools



# ************* Database Setup *************
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url, id="agno_assist_db")
# *******************************


# ************* Description and Instructions *************
description = dedent(
    """\
    You are a team of agents that can assist the user with their tasks.
    """
)

instructions = dedent(
    """\
    Help the user with their question.
    The knowledge agent is responsible for answering questions about the knowledge base and is not allowed to answer with anything else except what is in the knowledge base.
    If the user asks a question that is not in the knowledge base, you should say that you don't know the answer.
    If the user instructs you to update the knowledge base, you should update the knowledge base with the information provided by the user.

    If the user provides media, you should use the multimodal agent to analyse the media and provide a summary of the content.

    If the user asks a question about a Github repository, you should use the github agent to answer the question.

    If a user asks to create a task, you should use the task manager agent to create the task. If they provide a statement
    of something that looks like something that needs to be remembered, let the taks manager agent know to store it.
    """
)
# *******************************

# ************* Agents *************

multimodal_agent = Agent(
    name="Multimodal Agent",
    model=Gemini(id="gemini-2.0-flash"),
    instructions=dedent("""
    You are a multimodal agent that can answer questions and assist the user with their tasks.
    You analyse given input media and provide a summary of the content.
    """),
)
web_search_agent = Agent(
    name="Web Search Agent",
    model=OpenAIChat(id="gpt-5-nano"),
    tools=[DuckDuckGoTools()],
)
github_agent = Agent(
    name="Github Agent",
    model=OpenAIChat(id="gpt-5-nano"),
    tools=[GithubTools()],
    debug_mode=True,
)
task_manager_agent = Agent(
    name="Task Manager Agent",
    db=db,
    instructions=dedent("""
    You are a task manager agent that can assist the user with their tasks.
    You store tasks, and retrieve them when the user asks for them.
    """),
    model=OpenAIChat(id="gpt-5-nano"),
    debug_mode=True,
)
# ************* Team *************
personal_assistant_team = Team(
    db=db,
    name="Personal Assistant Team",
    model=OpenAIChat(id="gpt-5-mini"),
    description=description,
    instructions=instructions,
    members=[knowledge_agent, multimodal_agent, web_search_agent, github_agent, task_manager_agent],
    respond_directly=False,
    add_history_to_context=True,
    read_team_history=True,
    debug_mode=True,
)
# *******************************
