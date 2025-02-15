"""
Sage: An Answer Engine
---------------------------------
This example shows how to build Sage, a Perplexity-like Answer Engine that intelligently
determines whether to perform a web search or conduct a deep analysis using ExaTools based on the user's query.
It also prompts the user to save the generated answer to a file using FileTools.

Usage Examples:
---------------
1. Quick real-time search:
   sage = get_sage()
   answer = sage.run("What are the latest trends in renewable energy?")

2. In-depth analysis:
   sage = get_sage()
   answer = sage.run("Perform a detailed analysis of the impact of climate change on agriculture.")

3. Combined query with saving option:
   sage = get_sage()
   answer = sage.run("What's new in AI regulations in the EU and could you save the summary for me?")

Sage integrates:
  - DuckDuckGoTools for real-time web searches.
  - ExaTools for structured, in-depth analysis.
  - FileTools for saving the output upon user confirmation.

Sage intelligently selects the optimal tool based on query complexity to provide insightful, comprehensive answers.
"""

import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

# Importing the Agent and model classes
from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.models.google import Gemini
from agno.models.groq import Groq
from agno.models.openai import OpenAIChat

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


def get_sage(
    user_id: Optional[str] = None,
    model_id: str = "openai:gpt-4o",
    session_id: Optional[str] = None,
    num_history_responses: int = 5,
    debug_mode: bool = True,
) -> Agent:
    """
    Returns an instance of Sage, the Answer Engine Agent with integrated tools for web search,
    deep contextual analysis, and file management.

    Sage will:
      - Decide whether a query requires a real-time web search (using DuckDuckGoTools)
        or an in-depth analysis (using ExaTools).
      - Generate a comprehensive answer that includes:
          • A direct, succinct answer.
          • Detailed explanations and supporting evidence.
          • Examples and clarification of misconceptions.
      - Prompt the user:
            "Would you like to save this answer to a file? (yes/no)"
        If confirmed, it will use FileTools to save the answer in markdown format in the output directory.

    Args:
        user_id: Optional identifier for the user.
        model_id: Model identifier in the format 'provider:model_name' (e.g., "openai:gpt-4o").
        session_id: Optional session identifier for tracking conversation history.
        num_history_responses: Number of previous responses to include for context.
        debug_mode: Enable logging and debug features.

    Returns:
        An instance of the configured Agent.
    """

    # Parse model provider and name
    provider, model_name = model_id.split(":")

    # Select appropriate model class based on provider
    if provider == "openai":
        model = OpenAIChat(id=model_name)
    elif provider == "google":
        model = Gemini(id=model_name)
    elif provider == "anthropic":
        model = Claude(id=model_name)
    elif provider == "groq":
        model = Groq(id=model_name)
    else:
        raise ValueError(f"Unsupported model provider: {provider}")

    # Tools for Sage
    tools = [
        ExaTools(
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

    return Agent(
        name="Sage",
        model=model,
        user_id=user_id,
        session_id=session_id or str(uuid.uuid4()),
        storage=agent_storage,
        tools=tools,
        # Allow Sage to read both chat history and tool call history for better context.
        read_chat_history=True,
        read_tool_call_history=True,
        # Append previous conversation responses into the new messages for context.
        add_history_to_messages=True,
        num_history_responses=num_history_responses,
        add_datetime_to_instructions=True,
        add_name_to_instructions=True,
        description=AGENT_DESCRIPTION,
        instructions=AGENT_INSTRUCTIONS,
        expected_output=EXPECTED_OUTPUT_TEMPLATE,
        debug_mode=debug_mode,
        markdown=True,
    )
