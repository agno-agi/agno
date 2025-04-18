from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent
from typing import List, Optional

from agents import get_agent
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
from agno.tools.reasoning import ReasoningTools
from agno.utils.log import logger
from agno.vectordb.lancedb import LanceDb, SearchType
from tools import get_toolkit

cwd = Path(__file__).parent.resolve()
tmp_dir = cwd.joinpath("tmp")
tmp_dir.mkdir(exist_ok=True, parents=True)

# Define paths for storage, memory and knowledge
STORAGE_PATH = tmp_dir.joinpath("uagi_sessions.db")
MEMORY_PATH = tmp_dir.joinpath("uagi_memory.db")
KNOWLEDGE_PATH = tmp_dir.joinpath("uagi_knowledge")


@dataclass
class UAgIConfig:
    user_id: str
    model_id: str = "anthropic:claude-3-7-sonnet-latest"
    tools: Optional[List[str]] = None
    agents: Optional[List[str]] = None


uagi_memory = Memory(
    db=SqliteMemoryDb(table_name="uagi_memory", db_file=str(MEMORY_PATH))
)
uagi_storage = SqliteStorage(db_file=str(STORAGE_PATH), table_name="uagi_sessions")
uagi_knowledge = AgentKnowledge(
    vector_db=LanceDb(
        table_name="uagi_knowledge",
        uri=str(KNOWLEDGE_PATH),
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    )
)


def create_uagi(
    config: UAgIConfig, session_id: Optional[str] = None, debug_mode: bool = True
) -> Team:
    """Returns an instance of the Universal Agent Interface (UAgI)

    Args:
        config: UAgI configuration
        session_id: Session identifier
        debug_mode: Enable debug logging
    """
    # Parse model provider and name
    provider, model_name = config.model_id.split(":")

    # Create model class based on provider
    model = None
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
    if model is None:
        raise ValueError(f"Failed to create model instance for {config.model_id}")

    tools: List[Toolkit] = [ReasoningTools(add_instructions=True)]
    if config.tools:
        for tool_name in config.tools:
            tool = get_toolkit(tool_name)
            if tool is not None:
                tools.append(tool)
            else:
                logger.warning(f"Tool {tool_name} not found")

    agents: List[Agent] = []
    if config.agents:
        for agent_name in config.agents:
            agent = get_agent(agent_name, model, uagi_memory, uagi_knowledge)
            if agent is not None:
                agents.append(agent)
            else:
                logger.warning(f"Agent {agent_name} not found")

    description = dedent("""\
    You are an advanced AI System called `Universal Agent Interface` (UAgI).
    You provide a unified interface to a team of AI Agents, that you coordinate to assist the user in the best way possible.

    Keep your responses short and to the point, while maintaining a conversational tone.
    You are able to handle easy conversations as well as complex requests by delegating tasks to the appropriate team members.
    You are also capable of handling errors and edge cases and are able to provide helpful feedback to the user.\
    """)
    instructions: List[str] = [
        "Your goal is to coordinate the team to assist the user in the best way possible.",
        "If the user sends a conversational message like 'Hello', 'Hi', 'How are you', 'What is your name', etc., you should respond in a friendly and engaging manner.",
        "If the user asks for something simple, like updating memory, you can do it directly without Thinking and Analyzing.",
        "Keep your responses short and to the point, while maintaining a conversational tone.",
        "If the user asks for something complex, **think** and determine if:\n"
        " - You can answer by using a tool available to you\n"
        " - You need to search the knowledge base\n"
        " - You need to search the internet\n"
        " - You need to delegate the task to a team member\n"
        " - You need to ask a clarifying question",
        "You also have to a knowledge base of information provided by the user. If the user asks about a topic that might be in the knowledge base, first ALWAYS search your knowledge base using the `search_knowledge_base` tool.",
        "As a default, you should always search your knowledge base first, before searching the internet.",
        "If you dont find relevant information in your knowledge base, use the `duckduckgo_search` tool to search the internet.",
        "If the users message is unclear, ask clarifying questions to get more information.",
        "Based on the user request and the available team members, decide which member(s) should handle the task.",
        "Coordinate the execution of the task among the selected team members.",
        "Synthesize the results from the team members and provide a final, coherent answer to the user.",
        "Do not use phrases like 'based on my knowledge' or 'depending on the information'.",
    ]

    uagi = Team(
        name="Universal Agent Interface",
        mode="coordinate",
        model=model,
        user_id=config.user_id,
        session_id=session_id,
        tools=tools,
        members=agents,
        memory=uagi_memory,
        storage=uagi_storage,
        knowledge=uagi_knowledge,
        description=description,
        instructions=instructions,
        enable_team_history=True,
        read_team_history=True,
        num_of_interactions_from_history=3,
        show_members_responses=True,
        enable_agentic_memory=True,
        markdown=True,
        debug_mode=debug_mode,
    )

    agent_names = [a.name for a in agents] if agents else []
    logger.info(f"UAgI created with members: {agent_names}")
    return uagi
