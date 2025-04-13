import os
import uuid
from pathlib import Path
from textwrap import dedent
from typing import List, Optional

import streamlit as st
from agno.agent import Agent
from agno.embedder.openai import OpenAIEmbedder
from agno.knowledge import AgentKnowledge
from agno.memory.v2 import Memory
from agno.memory.v2.db.sqlite import SqliteMemoryDb
from agno.models.anthropic import Claude
from agno.models.google import Gemini
from agno.models.groq import Groq
from agno.models.openai import OpenAIChat
from agno.storage.sqlite import SqliteStorage
from agno.team import Team
from agno.tools import Toolkit
from agno.tools.calculator import CalculatorTools
from agno.tools.duckdb import DuckDbTools
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.exa import ExaTools
from agno.tools.file import FileTools
from agno.tools.python import PythonTools
from agno.tools.shell import ShellTools
from agno.tools.yfinance import YFinanceTools
from agno.utils.log import logger
from agno.vectordb.qdrant import Qdrant
from dotenv import load_dotenv

cwd = Path(__file__).parent.resolve()
tmp_dir = cwd.joinpath("tmp")
tmp_dir.mkdir(exist_ok=True, parents=True)

# Define paths for SQLite
SQLITE_DB_PATH = cwd.joinpath("tmp/llm_os_sessions.db")
SQLITE_MEMORY_DB_PATH = cwd.joinpath("tmp/llm_os_memory.db")
QDRANT_COLLECTION = "llm_os_knowledge"


def get_llm_os(
    model_id: str = "openai:gpt-4o",
    calculator: bool = False,
    ddg_search: bool = False,
    file_tools: bool = False,
    shell_tools: bool = False,
    data_analyst: bool = True,
    python_agent_enable: bool = True,
    research_agent_enable: bool = False,
    investment_agent_enable: bool = True,
    # Pass user_id and session_id again
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    debug_mode: bool = True,
) -> Team:
    final_session_id = session_id if session_id is not None else str(uuid.uuid4())
    logger.info(f"-*- Creating/Loading {model_id} LLM OS Team -*-")
    logger.info(f"Session: {final_session_id} User: {user_id}")

    leader_tools: List[Toolkit] = []
    leader_instructions: List[str] = [
        "You are the coordinator of a team of AI Agents called `LLM-OS`.",
        "Your goal is to coordinate the team to assist the user in the best way possible.",
        "When the user sends a message, first **think** and determine if:\n"
        " - You can answer by using a tool available to you\n"
        " - You need to search the knowledge base\n"
        " - You need to search the internet\n"
        " - You need to delegate the task to a team member\n"
        " - You need to ask a clarifying question",
        "If the user asks about a topic, first ALWAYS search your knowledge base using the `search_knowledge_base` tool.",
        "If you dont find relevant information in your knowledge base, use the `duckduckgo_search` tool to search the internet.",
        "If the users message is unclear, ask clarifying questions to get more information.",
        "Based on the user request and the available team members, decide which member(s) should handle the task.",
        "If the user asks for an investment report, delegate the task to the `Investment_Agent`.",
        "If the user asks for a research report, delegate the task to the `Research_Agent`.",
        "Coordinate the execution of the task among the selected team members.",
        "Synthesize the results from the team members and provide a final, coherent answer to the user.",
        "Do not use phrases like 'based on my knowledge' or 'depending on the information'.",
        "Remember you are stateless, your memory resets often. Do not refer to previous interactions unless the history is explicitly provided in the current turn.",
    ]
    members: List[Agent] = []

    llm_instance = None
    provider_prefix = "openai:"  # Default
    actual_model_id = model_id

    if ":" in model_id:
        parts = model_id.split(":", 1)
        provider_prefix = parts[0] + ":"
        actual_model_id = parts[1]
    else:
        logger.warning(
            f"No provider prefix found in model_id '{model_id}'. Assuming 'openai:'."
        )
        provider_prefix = "openai:"
        actual_model_id = model_id

    logger.info(
        f"Selected LLM Provider: {provider_prefix}, Model ID: {actual_model_id}"
    )

    if provider_prefix == "openai:":
        llm_instance = OpenAIChat(id=actual_model_id)
    elif provider_prefix == "anthropic:":
        llm_instance = Claude(id=actual_model_id)
    elif provider_prefix == "google:":
        llm_instance = Gemini(id=actual_model_id)
    elif provider_prefix == "groq:":
        llm_instance = Groq(id=actual_model_id)
    else:
        logger.error(f"Unsupported LLM provider prefix in model_id: {provider_prefix}")
        st.error(f"Unsupported LLM provider: {provider_prefix}")
        return None  # Cannot proceed

    if llm_instance is None:
        logger.error(f"LLM instance could not be created for model_id: {model_id}")
        st.error(f"Failed to create LLM instance for {model_id}")
        return None

    memory_db = SqliteMemoryDb(table_name="memory", db_file=SQLITE_MEMORY_DB_PATH)
    memory = Memory(model="gemini-2.0-flash-exp", db=memory_db)

    # Add leader tools
    if calculator:
        leader_tools.append(CalculatorTools(enable_all=True))
        leader_instructions.append(
            "You have access to Calculator tools for basic arithmetic."
        )
    if ddg_search:
        leader_tools.append(DuckDuckGoTools(fixed_max_results=3))
        leader_instructions.append(
            "You can use `duckduckgo_search` for general web searches and `duckduckgo_news` for recent news."
        )
    if shell_tools:
        leader_tools.append(ShellTools())
        leader_instructions.append(
            "You can use the `run_shell_command` tool to run shell commands."
        )
    if file_tools:
        leader_tools.append(FileTools(base_dir=cwd))
        leader_instructions.append(
            "You can use the `read_file`, `save_file`, and `list_files` tools."
        )

    # Create team members
    if data_analyst:
        data_analyst_agent: Agent = Agent(
            name="Data_Analyst",
            model=llm_instance,
            tools=[DuckDbTools()],
            show_tool_calls=True,
            instructions=[
                "You are a Data Analyst. Your goal is to answer questions about movie data.",
                "Use the provided DuckDbTools to query the data.",
                "The data is located at: https://agno-public.s3.amazonaws.com/demo_data/IMDB-Movie-Data.csv",
            ],
            debug_mode=debug_mode,
            memory=memory,  # Add memory to member
        )
        members.append(data_analyst_agent)
        leader_instructions.append(
            "To answer questions about movies, delegate the task to the `Data_Analyst`."
        )

    if python_agent_enable:
        python_agent: Agent = Agent(
            name="Python_Agent",
            model=llm_instance,
            tools=[PythonTools(base_dir=Path("tmp/python")), FileTools(base_dir=cwd)],
            show_tool_calls=True,
            instructions=[
                "You are a Python code execution specialist.",
                "Write and run Python code using the `save_to_file_and_run` tool to fulfill the user's request.",
                "IMPORTANT: If the user asks you to read or process a file that you did not create yourself (e.g., a file created by the coordinator), you MUST use the `read_file` tool FIRST to get its content.",
                "The `read_file` tool operates from the application's main directory. Use the filename provided by the coordinator directly with `read_file`.",
                "Once you have the file content from `read_file`, incorporate that content into the Python script you write for `save_to_file_and_run`.",
                "Do NOT attempt to open files directly using Python's `open()` function unless it's a file you are creating within the script itself.",
            ],
            debug_mode=debug_mode,
            memory=memory,  # Add memory to member
        )
        members.append(python_agent)
        leader_instructions.append(
            "To write and run Python code, delegate the task to the `Python_Agent`."
        )
        leader_instructions.append(
            "When delegating a task involving reading a file to the Python_Agent, ensure you provide the correct filename created by your own `save_file` tool."
        )

    if research_agent_enable:
        research_agent = Agent(
            name="Research_Agent",
            role="Write a research report on a given topic",
            model=llm_instance,
            description="You are a Senior New York Times researcher tasked with writing a cover story research report.",
            instructions=[
                "For a given topic, use the `search_exa` to get the top 10 search results.",
                "Carefully read the results and generate a final - NYT cover story worthy report in the <report_format> provided below.",
                "Make your report engaging, informative, and well-structured.",
                "Remember: you are writing for the New York Times, so the quality of the report is important.",
            ],
            expected_output=dedent(
                """\
            <report_format>
            ## Title

            - **Overview** Brief introduction of the topic.
            - **Importance** Why is this topic significant now?

            ### Section 1
            - **Detail 1**
            - **Detail 2**

            ### Section 2
            - **Detail 1**
            - **Detail 2**

            ## Conclusion
            - **Summary of report:** Recap of the key findings from the report.
            - **Implications:** What these findings mean for the future.

            ## References
            - [Reference 1](Link to Source)
            - [Reference 2](Link to Source)
            </report_format>
            """
            ),
            tools=[ExaTools(num_results=3, text_length_limit=1000)],
            markdown=True,
            debug_mode=debug_mode,
            memory=memory,  # Add memory to member
        )
        members.append(research_agent)
        leader_instructions.append(
            "To generate a research report, delegate the task to the `Research_Agent`."
        )

    if investment_agent_enable:
        investment_agent = Agent(
            name="Investment_Agent",
            role="Write an investment report on a given company (stock) symbol",
            model=llm_instance,
            description="You are a Senior Investment Analyst for Goldman Sachs tasked with writing an investment report for a very important client.",
            instructions=[
                "For a given stock symbol, get the stock price, company information, analyst recommendations, and company news using the available tools.",
                "Carefully read the research and generate a final - Goldman Sachs worthy investment report in the <report_format> provided below.",
                "Provide thoughtful insights and recommendations based on the research.",
                "When you share numbers, make sure to include the units (e.g., millions/billions) and currency.",
                "REMEMBER: This report is for a very important client, so the quality of the report is important.",
            ],
            expected_output=dedent(
                """\
            <report_format>
            ## [Company Name]: Investment Report

            ### **Overview**
            {give a brief introduction of the company and why the user should read this report}
            {make this section engaging and create a hook for the reader}

            ### Core Metrics
            {provide a summary of core metrics and show the latest data}
            - Current price: {current price}
            - 52-week high: {52-week high}
            - 52-week low: {52-week low}
            - Market Cap: {Market Cap} in billions
            - P/E Ratio: {P/E Ratio}
            - Earnings per Share: {EPS}
            - 50-day average: {50-day average}
            - 200-day average: {200-day average}
            - Analyst Recommendations: {buy, hold, sell} (number of analysts)

            ### Financial Performance
            {analyze the company's financial performance}

            ### Growth Prospects
            {analyze the company's growth prospects and future potential}

            ### News and Updates
            {summarize relevant news that can impact the stock price}

            ### [Summary]
            {give a summary of the report and what are the key takeaways}

            ### [Recommendation]
            {provide a recommendation on the stock along with a thorough reasoning}

            </report_format>
            """
            ),
            tools=[YFinanceTools, DuckDuckGoTools(fixed_max_results=5)],
            markdown=True,
            debug_mode=debug_mode,
            memory=memory,  # Add memory to member
        )
        members.append(investment_agent)
        leader_instructions.append(
            "To generate an investment report, delegate the task to the `Investment_Agent`."
        )

    team_storage = SqliteStorage(
        db_file=str(SQLITE_DB_PATH),
        table_name="team_sessions",
        mode="agent",
    )

    try:
        vector_db = Qdrant(location=":memory:", collection=QDRANT_COLLECTION)
        vector_db.create()
        logger.info(f"In-memory Qdrant collection '{vector_db.collection}' ensured.")
    except Exception as e:
        logger.error(f"Fatal error getting In-Memory Qdrant: {e}")
        st.error(f"Failed to initialize Knowledge Base storage: {e}")
        return None

    knowledge = AgentKnowledge(vector_db=vector_db, embedder=OpenAIEmbedder())

    llm_os_team = Team(
        name="LLM_OS_Team",
        team_id=final_session_id,
        user_id=user_id,
        model=llm_instance,
        mode="coordinate",
        members=members,
        tools=leader_tools,
        instructions=leader_instructions,
        storage=team_storage,
        knowledge=knowledge,
        enable_team_history=True,
        num_of_interactions_from_history=5,
        show_tool_calls=True,
        show_members_responses=True,
        markdown=True,
        debug_mode=debug_mode,
        memory=memory,
        enable_agentic_memory=True,
        enable_session_summaries=True,
    )

    # Log the names of the members being added to the team
    member_names = [member.name for member in members] if members else []
    logger.info(f"LLM OS Team created with members: {member_names}")

    return llm_os_team
