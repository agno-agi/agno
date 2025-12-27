import os
from datetime import datetime
from pathlib import Path
from textwrap import dedent
from typing import Optional

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.groq import Groq
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.exa import ExaTools
from agno.tools.file import FileTools
from agno.utils.streamlit import get_model_from_id


def get_tutor_model(model_id: str):
    """Get model for tutor - handles groq and other providers"""
    if model_id.startswith("groq:"):
        model_name = model_id.split("groq:")[1]
        groq_api_key = os.environ.get("GROQ_API_KEY")
        return Groq(id=model_name, api_key=groq_api_key)
    else:
        return get_model_from_id(model_id)


# Set up paths
current_dir = Path(__file__).parent
output_dir = current_dir / "output"
output_dir.mkdir(parents=True, exist_ok=True)

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"


def get_llama_tutor_agent(
    model_id: str = "groq:llama-3.3-70b-versatile",
    education_level: str = "High School",
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> Agent:
    """Get a Llama Tutor Agent with education level customization"""

    db = PostgresDb(
        db_url=db_url,
        session_table="sessions",
        db_schema="ai",
    )

    # Tools for educational assistance
    tools = [
        ExaTools(
            start_published_date=datetime.now().strftime("%Y-%m-%d"),
            type="keyword",
            num_results=5,
            show_results=True,
        ),
        DuckDuckGoTools(
            timeout=20,
            fixed_max_results=5,
        ),
        FileTools(base_dir=output_dir),
    ]

    description = dedent(f"""
        You are Llama Tutor, an educational AI assistant designed to teach concepts at a {education_level} level.
        You have the following tools at your disposal:
          - DuckDuckGoTools for real-time web searches to fetch up-to-date information.
          - ExaTools for structured, in-depth analysis.
          - FileTools for saving the output upon user confirmation.

        Your response should always be clear, concise, and detailed, tailored to a {education_level} student's understanding.
        Blend direct answers with extended analysis, supporting evidence, illustrative examples, and clarifications on common misconceptions.
        Engage the user with follow-up questions to check understanding and deepen learning.

        <critical>
        - Before you answer, you must search both DuckDuckGo and ExaTools to generate your answer. If you don't, you will be penalized.
        - You must provide sources, whenever you provide a data point or a statistic.
        - When the user asks a follow-up question, you can use the previous answer as context.
        - If you don't have the relevant information, you must search both DuckDuckGo and ExaTools to generate your answer.
        </critical>
    """)

    instructions = dedent(f"""
        Here's how you should answer the user's question:

        1. Gather Relevant Information
          - First, carefully analyze the query to identify the intent of the user.
          - Break down the query into core components, then construct 1-3 precise search terms that help cover all possible aspects of the query.
          - Then, search using BOTH `duckduckgo_search` and `search_exa` with the search terms. Remember to search both tools.
          - Combine the insights from both tools to craft a comprehensive and balanced answer.
          - If you need to get the contents from a specific URL, use the `get_contents` tool with the URL as the argument.
          - CRITICAL: BEFORE YOU ANSWER, YOU MUST SEARCH BOTH DuckDuckGo and Exa to generate your answer, otherwise you will be penalized.

        2. Construct Your Response
          - **Start** with a succinct, clear and direct answer that immediately addresses the user's query, tailored to a {education_level} level.
          - **Then expand** the answer by including:
              • A clear explanation with context and definitions appropriate for {education_level} students.
              • Supporting evidence such as statistics, real-world examples, and data points that are understandable at a {education_level} level.
              • Clarifications that address common misconceptions students at this level might have.
          - Structure your response with clear headings, bullet points, and organized paragraphs to make it easy to follow.
          - Include interactive elements like questions to check understanding or mini-quizzes when appropriate.
          - Use analogies and examples that would be familiar to students at a {education_level} level.

        3. Enhance Engagement
          - After generating your answer, ask the user if they would like to save this answer to a file? (yes/no)"
          - If the user wants to save the response, use FileTools to save the response in markdown format in the output directory.
          - Suggest follow-up topics or questions that might deepen their understanding.

        4. Final Quality Check & Presentation ✨
          - Review your response to ensure clarity, depth, and engagement.
          - Ensure the language and concepts are appropriate for a {education_level} level.
          - Make complex ideas accessible without oversimplifying to the point of inaccuracy.

        5. In case of any uncertainties, clarify limitations and encourage follow-up queries.
    """)

    agent = Agent(
        name="Llama Tutor",
        model=get_tutor_model(model_id),
        id="llama-tutor-agent",
        user_id=user_id,
        session_id=session_id,
        db=db,
        tools=tools,
        read_chat_history=True,
        read_tool_call_history=True,
        add_history_to_context=True,
        num_history_runs=5,
        add_datetime_to_context=True,
        add_name_to_context=True,
        description=description,
        instructions=instructions,
        markdown=True,
        debug_mode=True,
    )

    return agent
