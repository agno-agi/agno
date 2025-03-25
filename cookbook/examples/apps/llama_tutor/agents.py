"""
Llama tutor integrates:
  - DuckDuckGoTools for real-time web searches.
  - ExaTools for structured, in-depth analysis.
  - FileTools for saving the output upon user confirmation.
"""

import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv(override=True)

# Importing the Agent and model classes
from agno.agent import Agent
from agno.models.groq import Groq

# Importing storage and tool classes
from agno.storage.agent.sqlite import SqliteAgentStorage
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.exa import ExaTools
from agno.tools.file import FileTools

# Import the Agent template
from prompts import AGENT_DESCRIPTION, AGENT_INSTRUCTIONS, EXPECTED_OUTPUT_TEMPLATE

# ************* Setup Paths *************
# Define the current working directory and output directory for saving files
cwd = Path(__file__).parent
output_dir = cwd.joinpath("output")
# Create output directory if it doesn't exist
output_dir.mkdir(parents=True, exist_ok=True)
# Create tmp directory if it doesn't exist
tmp_dir = cwd.joinpath("tmp")
tmp_dir.mkdir(parents=True, exist_ok=True)
# *************************************

# ************* Agent Storage *************
# Configure SQLite storage for agent sessions
agent_storage = SqliteAgentStorage(
    table_name="answer_engine_sessions",  # Table to store agent sessions
    db_file=str(tmp_dir.joinpath("agents.db")),  # SQLite database file
)
# *************************************


def tutor_agent(
    user_id: Optional[str] = None,
    model_id: str = "groq:llama-3.3-70b-versatile",
    session_id: Optional[str] = None,
    num_history_responses: int = 5,
    debug_mode: bool = True,
    education_level: str = "High School",
) -> Agent:
    """
    Returns an instance of Llama Tutor, an educational AI assistant with integrated tools for web search,
    deep contextual analysis, and file management.

    Llama Tutor will:
      - Use DuckDuckGoTools for real-time web searches and ExaTools for in-depth analysis to gather information.
      - Generate comprehensive educational answers tailored to the specified education level that include:
          • Direct, succinct answers appropriate for the student's level.
          • Detailed explanations with supporting evidence.
          • Examples and clarification of common misconceptions.
          • Interactive elements like questions to check understanding.
      - Prompt the user:
            "Would you like to save this answer to a file? (yes/no)"
        If confirmed, it will use FileTools to save the answer in markdown format in the output directory.

    Args:
        user_id: Optional identifier for the user.
        model_id: Model identifier in the format 'groq:model_name' (e.g., "groq:llama-3.3-70b-versatile").
                 Will always use Groq with a Llama model regardless of provider specified.
        session_id: Optional session identifier for tracking conversation history.
        num_history_responses: Number of previous responses to include for context.
        debug_mode: Enable logging and debug features.
        education_level: Education level for tailoring responses (e.g., "Elementary School", "High School", "College").

    Returns:
        An instance of the configured Agent.
    """

    # Parse model provider and name
    provider, model_name = model_id.split(":")

    # Always use Groq with Llama model
    groq_api_key = os.environ.get("GROQ_API_KEY")

    # Default to llama-3.3-70b-versatile if the model name doesn't contain "llama"
    if "llama" not in model_name.lower():
        model_name = "llama-3.3-70b-versatile"

    model = Groq(id=model_name, api_key=groq_api_key)

    # Get Exa API key from environment variable
    exa_api_key = os.environ.get("EXA_API_KEY")

    # Tools for Llama Tutor
    tools = [
        ExaTools(
            api_key=exa_api_key,
            start_published_date=datetime.now().strftime("%Y-%m-%d"),
            type="keyword",
            num_results=10,
        ),
        DuckDuckGoTools(
            timeout=20,
            fixed_max_results=5,
        ),
        FileTools(base_dir=output_dir),
    ]

    # Modify the description to include the education level
    tutor_description = f"""You are Llama Tutor, an educational AI assistant designed to teach concepts at a {education_level} level.
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
    - Always adapt your explanations to a {education_level} level of understanding.
    </critical>"""

    # Modify the instructions to include the education level
    tutor_instructions = f"""Here's how you should answer the user's question:

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

    5. In case of any uncertainties, clarify limitations and encourage follow-up queries."""

    return Agent(
        name="Llama Tutor",
        model=model,
        user_id=user_id,
        session_id=session_id or str(uuid.uuid4()),
        storage=agent_storage,
        tools=tools,
        # Allow Llama Tutor to read both chat history and tool call history for better context.
        read_chat_history=True,
        read_tool_call_history=True,
        # Append previous conversation responses into the new messages for context.
        add_history_to_messages=True,
        num_history_responses=num_history_responses,
        add_datetime_to_instructions=True,
        add_name_to_instructions=True,
        description=tutor_description,
        instructions=tutor_instructions,
        expected_output=EXPECTED_OUTPUT_TEMPLATE,
        debug_mode=debug_mode,
        markdown=True,
    )
