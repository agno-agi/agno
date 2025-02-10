import os
from pathlib import Path
from textwrap import dedent
from typing import List, Optional

from agno.agent import Agent
from agno.embedder.openai import OpenAIEmbedder
from agno.knowledge import AgentKnowledge
from agno.models.openai import OpenAIChat
from agno.storage.agent.postgres import PostgresAgentStorage
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

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
cwd = Path(__file__).parent.resolve()
scratch_dir = cwd.joinpath("scratch")
if not scratch_dir.exists():
    scratch_dir.mkdir(exist_ok=True, parents=True)


def get_llm_os(
    model_id: str = "gpt-4o",
    calculator: bool = False,
    ddg_search: bool = False,
    file_tools: bool = False,
    shell_tools: bool = False,
    data_analyst: bool = False,
    python_agent_enable: bool = False,
    research_agent_enable: bool = False,
    investment_agent_enable: bool = False,
    user_id: Optional[str] = None,
    debug_mode: bool = True,
) -> Agent:
    logger.info(f"-*- Creating {model_id} LLM OS -*-")

    tools: List[Toolkit] = []
    extra_instructions: List[str] = []

    if calculator:
        tools.append(
            CalculatorTools(
                enable_all=True
                # enables addition, subtraction, multiplication, division, check prime, exponential, factorial, square root
            )
        )
    if ddg_search:
        tools.append(DuckDuckGoTools(fixed_max_results=3))
    if shell_tools:
        tools.append(ShellTools())
        extra_instructions.append(
            "You can use the `run_shell_command` tool to run shell commands. For example, `run_shell_command(args='ls')`."
        )
    if file_tools:
        tools.append(FileTools(base_dir=cwd))
        extra_instructions.append(
            "You can use the `read_file` tool to read a file, `save_file` to save a file, and `list_files` to list files in the working directory."
        )

    # Add team members available to the LLM OS
    team: List[Agent] = []

    if data_analyst:
        data_analyst_agent: Agent = Agent(
            tools=[DuckDbTools()],
            show_tool_calls=True,
            instructions="Use this file for Movies data: https://agno-public.s3.amazonaws.com/demo_data/IMDB-Movie-Data.csv",
        )
        team.append(data_analyst_agent)
        extra_instructions.append(
            "To answer questions about my favorite movies, delegate the task to the `Data Analyst`."
        )

    if python_agent_enable:
        python_agent: Agent = Agent(
            tools=[PythonTools(base_dir=Path("tmp/python"))],
            show_tool_calls=True,
            instructions="To write and run Python code, delegate the task to the `Python Agent`.",
        )

        team.append(python_agent)
        extra_instructions.append(
            "To write and run Python code, delegate the task to the `Python Agent`."
        )
    if research_agent_enable:
        research_agent = Agent(
            name="Research Agent",
            role="Write a research report on a given topic",
            model=OpenAIChat(id=model_id),
            description="You are a Senior New York Times researcher tasked with writing a cover story research report.",
            instructions=[
                "For a given topic, use the `search_exa` to get the top 10 search results.",
                "Carefully read the results and generate a final - NYT cover story worthy report in the <report_format> provided below.",
                "Make your report engaging, informative, and well-structured.",
                "Remember: you are writing for the New York Times, so the quality of the report is important.",
            ],
            expected_output=dedent(
                """\
            An engaging, informative, and well-structured report in the following format:
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
        )
        team.append(research_agent)
        extra_instructions.append(
            "To write a research report, delegate the task to the `Research Agent`. "
            "Return the report in the <report_format> to the user as is, without any additional text like 'here is the report'."
        )

    if investment_agent_enable:
        investment_agent = Agent(
            name="Investment Agent",
            role="Write an investment report on a given company (stock) symbol",
            model=OpenAIChat(id=model_id),
            description="You are a Senior Investment Analyst for Goldman Sachs tasked with writing an investment report for a very important client.",
            instructions=[
                "For a given stock symbol, get the stock price, company information, analyst recommendations, and company news",
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
            tools=[
                YFinanceTools(
                    stock_price=True,
                    company_info=True,
                    analyst_recommendations=True,
                    company_news=True,
                )
            ],
            markdown=True,
            debug_mode=debug_mode,
            add_datetime_to_instructions=True,
        )
        team.append(investment_agent)
        extra_instructions.extend(
            [
                "To get an investment report on a stock, delegate the task to the `Investment Agent`. "
                "Return the report in the <report_format> to the user without any additional text like 'here is the report'.",
                "Answer any questions they may have using the information in the report.",
                "Never provide investment advise without the investment report.",
            ]
        )

    # Create the LLM OS Agent
    llm_os = Agent(
        name="llm_os",
        model=OpenAIChat(id=model_id),
        user_id=user_id,
        tools=tools,
        team=team,
        description=dedent("""\
        You are the most advanced AI system in the world called `LLM-OS`.
        You have access to a set of tools and a team of AI Agents at your disposal.
        Your goal is to assist the user in the best way possible.\
        """),
        instructions=[
            "When the user sends a message, first **think** and determine if:\n"
            " - You can answer by using a tool available to you\n"
            " - You need to search the knowledge base\n"
            " - You need to search the internet\n"
            " - You need to delegate the task to a team member\n"
            " - You need to ask a clarifying question",
            "If the user asks about a topic, first ALWAYS search your knowledge base using the `search_knowledge_base` tool.",
            "If you dont find relevant information in your knowledge base, use the `duckduckgo_search` tool to search the internet.",
            "If the user asks to summarize the conversation or if you need to reference your chat history with the user, use the `get_chat_history` tool.",
            "If the users message is unclear, ask clarifying questions to get more information.",
            "Carefully read the information you have gathered and provide a clear and concise answer to the user.",
            "Do not use phrases like 'based on my knowledge' or 'depending on the information'.",
            "You can delegate tasks to an AI Agent in your team depending of their role and the tools available to them.",
            extra_instructions,
        ],
        storage=PostgresAgentStorage(db_url=db_url, table_name="llm_os_runs"),
        # Define the knowledge base
        knowledge=AgentKnowledge(
            vector_db=Qdrant(
                collection="llm_os_documents",
                embedder=OpenAIEmbedder(),
            ),
            num_documents=3,  # Retrieve 3 most relevant documents
        ),
        search_knowledge=True,  # This setting gives the LLM a tool to search the knowledge base for information
        read_chat_history=True,  # This setting gives the LLM a tool to get chat history
        add_history_to_messages=True,  # This setting adds chat history to the messages
        num_history_responses=5,
        markdown=True,
        add_datetime_to_instructions=True,  # This setting adds the current datetime to the instructions
        # Add an introductory Agent message
        introduction=dedent("""\
        Hi, I'm your LLM OS.
        I have access to a set of tools and AI Agents to assist you.
        Let's solve some problems together!\
        """),
        debug_mode=debug_mode,
    )

    return llm_os
