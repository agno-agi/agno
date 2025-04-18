"""
This example demonstrates a team of agents that can answer a variety of questions.

The team uses reasoning tools to reason about the questions and delegate to the appropriate agent.

The team consists of:
- A web agent that can search the web for information
- A finance agent that can get financial data
- A writer agent that can write content
- A calculator agent that can calculate
- A FastAPI assistant that can explain how to write FastAPI code
- A code execution agent that can execute code in a secure E2B sandbox
"""

import asyncio
from pathlib import Path
from textwrap import dedent

from agno.agent import Agent
from agno.embedder.openai import OpenAIEmbedder
from agno.knowledge.url import UrlKnowledge
from agno.models.anthropic import Claude
from agno.models.openai.chat import OpenAIChat
from agno.team.team import Team
from agno.tools.calculator import CalculatorTools
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.e2b import E2BTools
from agno.tools.file import FileTools
from agno.tools.github import GithubTools
from agno.tools.knowledge import KnowledgeTools
from agno.tools.pubmed import PubmedTools
from agno.tools.python import PythonTools
from agno.tools.reasoning import ReasoningTools
from agno.tools.yfinance import YFinanceTools
from agno.vectordb.lancedb.lance_db import LanceDb
from agno.vectordb.search import SearchType

cwd = Path(__file__).parent.resolve()

# Agent that can search the web for information
web_agent = Agent(
    name="Web Agent",
    role="Search the web for information",
    model=Claude(id="claude-3-5-sonnet-latest"),
    tools=[DuckDuckGoTools(cache_results=True)],
    instructions=["Always include sources"],
)

reddit_researcher = Agent(
    name="Reddit Researcher",
    role="Research a topic on Reddit",
    model=Claude(id="claude-3-5-sonnet-latest"),
    tools=[DuckDuckGoTools(cache_results=True)],
    add_name_to_instructions=True,
    instructions=dedent("""
    You are a Reddit researcher.
    You will be given a topic to research on Reddit.
    You will need to find the most relevant information on Reddit.
    """),
)

# Agent that can get financial data
finance_agent = Agent(
    name="Finance Agent",
    role="Get financial data",
    model=Claude(id="claude-3-5-sonnet-latest"),
    tools=[
        YFinanceTools(
            stock_price=True,
            analyst_recommendations=True,
            company_info=True,
            company_news=True,
        )
    ],
    instructions=["Use tables to display data"],
)

# Writer agent that can write content
writer_agent = Agent(
    name="Write Agent",
    role="Write content",
    model=Claude(id="claude-3-5-sonnet-latest"),
    description="You are an AI agent that can write content.",
    instructions=[
        "You are a versatile writer who can create content on any topic.",
        "When given a topic, write engaging and informative content in the requested format and style.",
        "If you receive mathematical expressions or calculations from the calculator agent, convert them into clear written text.",
        "Ensure your writing is clear, accurate and tailored to the specific request.",
        "Maintain a natural, engaging tone while being factually precise.",
        "Write something that would be good enough to be published in a newspaper like the New York Times.",
    ],
)

# Writer agent that can write content
medical_agent = Agent(
    name="Medical Agent",
    role="Write content",
    model=Claude(id="claude-3-5-sonnet-latest"),
    description="You are an AI agent that can write content.",
    tools=[PubmedTools()],
    instructions=[
        "You are a medical agent that can answer questions about medical topics.",
    ],
)

# Calculator agent that can calculate
calculator_agent = Agent(
    name="Calculator Agent",
    model=Claude(id="claude-3-5-sonnet-latest"),
    role="Calculate",
    tools=[
        CalculatorTools(
            add=True,
            subtract=True,
            multiply=True,
            divide=True,
            exponentiate=True,
            factorial=True,
            is_prime=True,
            square_root=True,
        )
    ],
)

agno_assist_knowledge = UrlKnowledge(
    urls=["https://docs.agno.com/llms-full.txt"],
    vector_db=LanceDb(
        uri="tmp/lancedb",
        table_name="agno_assist_knowledge",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)
agno_assist = Agent(
    name="Agno Assist",
    role="You help answer questions about the Agno framework.",
    model=OpenAIChat(id="gpt-4o"),
    instructions="Search your knowledge before answering the question. Help me to write working code for Agno Agents.",
    tools=[
        KnowledgeTools(
            knowledge=agno_assist_knowledge, add_instructions=True, add_few_shot=True
        ),
    ],
    add_history_to_messages=True,
    add_datetime_to_instructions=True,
)

github_agent = Agent(
    name="Github Agent",
    role="Do analysis on Github repositories",
    model=OpenAIChat(id="gpt-4o"),
    instructions=[
        "Use your tools to answer questions about the repo: agno-agi/agno",
        "Do not create any issues or pull requests unless explicitly asked to do so",
    ],
    tools=[
        GithubTools(
            list_pull_requests=True,
            list_issues=True,
            list_issue_comments=True,
            get_pull_request=True,
            get_issue=True,
            get_pull_request_comments=True,
        )
    ],
)

local_python_agent = Agent(
    name="Local Python Agent",
    role="Run Python code locally",
    model=OpenAIChat(id="gpt-4o"),
    instructions=[
        "Use your tools to run Python code locally",
    ],
    tools=[
        FileTools(base_dir=cwd),
        PythonTools(
            base_dir=Path(cwd), list_files=True, run_files=True, uv_pip_install=True
        ),
    ],
)


agent_team = Team(
    name="Multi-Purpose Team",
    mode="coordinate",
    model=Claude(id="claude-3-7-sonnet-latest"),
    tools=[
        ReasoningTools(add_instructions=True, add_few_shot=True),
    ],
    members=[
        web_agent,
        finance_agent,
        writer_agent,
        calculator_agent,
        agno_assist,
        github_agent,
        local_python_agent,
    ],
    instructions=[
        "You are a team of agents that can answer a variety of questions.",
        "You can use your member agents to answer the questions.",
        "You can also answer directly, you don't HAVE to forward the question to a member agent.",
        "Reason about more complex questions before delegating to a member agent.",
        "If the user is only being conversational, don't use any tools, just answer directly.",
    ],
    markdown=True,
    show_tool_calls=True,
    show_members_responses=True,
    enable_agentic_context=True,
    share_member_interactions=True,
)

if __name__ == "__main__":
    # Load the knowledge base (comment out after first run)
    # asyncio.run(agno_assist_knowledge.aload())

    # asyncio.run(agent_team.aprint_response("Hi! What are you capable of doing?"))

    # Python code execution
    # asyncio.run(agent_team.aprint_response(dedent("""What is the right way to implement an Agno Agent that searches Hacker News for good articles?
    #                                        Create a minimal example for me and test it locally to ensure it won't immediately crash.
    #                                        Make save the created code in a file called `./python/hacker_news_agent.py`.
    #                                        Don't mock anything. Use the real information from the Agno documentation."""), stream=True))

    # # Reddit research
    # asyncio.run(agent_team.aprint_response(dedent("""What should I be investing in right now?
    #                                        Find some popular subreddits and do some reseach of your own.
    #                                        Write a detailed report about your findings that could be given to a financial advisor."""), stream=True))

    # Github analysis
    # asyncio.run(agent_team.aprint_response(dedent("""List open pull requests in the agno-agi/agno repository.
    #                                        Find an issue that you think you can resolve and give me the issue number,
    #                                        your suggested solution and some code snippets."""), stream=True))

    # Medical research
    txt_path = Path(__file__).parent.resolve() / "medical_history.txt"
    loaded_txt = open(txt_path, "r").read()
    asyncio.run(
        agent_team.aprint_response(
            dedent(f"""I have a patient with the following medical information:\n {loaded_txt}
                                                    What is the most likely diagnosis?
                                                """),
            stream=True,
        )
    )
