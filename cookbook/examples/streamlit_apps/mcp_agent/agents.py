from pathlib import Path
from textwrap import dedent
from typing import List, Optional

from agno.agent import Agent
from agno.embedder.openai import OpenAIEmbedder
from agno.knowledge.url import UrlKnowledge
from agno.models.anthropic import Claude
from agno.models.google import Gemini
from agno.models.groq import Groq
from agno.models.openai import OpenAIChat
from agno.storage.agent.sqlite import SqliteAgentStorage
from agno.tools.mcp import MCPTools
from agno.vectordb.lancedb import LanceDb, SearchType

# ************* Setup Paths *************
# Define the current working directory
cwd = Path(__file__).parent
# Create a tmp directory for storing agent sessions and knowledge
tmp_dir = cwd.joinpath("tmp")
tmp_dir.mkdir(parents=True, exist_ok=True)
# *************************************

# ************* Agent Storage *************
# Store agent sessions in a SQLite database
agent_storage = SqliteAgentStorage(
    table_name="mcp_agent_sessions",  # Table to store agent sessions
    db_file=str(tmp_dir.joinpath("agents.db")),  # SQLite database file
)
# *************************************

# ************* Agent Knowledge *************
# Store MCP Documentation in a knowledge base
agent_knowledge = UrlKnowledge(
    urls=["https://modelcontextprotocol.io/llms-full.txt"],
    vector_db=LanceDb(
        uri=str(tmp_dir.joinpath("mcp_documentation")),
        table_name="mcp_documentation",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)
# *************************************


def get_mcp_agent(
    user_id: Optional[str] = None,
    model_str: str = "openai:gpt-4o",
    session_id: Optional[str] = None,
    num_history_responses: int = 5,
    mcp_tools: Optional[List[MCPTools]] = None,
    mcp_server_ids: Optional[List[str]] = None,
    debug_mode: bool = True,
) -> Agent:
    model = get_model_for_provider(model_str)

    description = dedent("""\
        You are UAgI, a universal MCP (Model Context Protocol) agent designed to interact with MCP servers.
        You can connect to various MCP servers to access resources and execute tools.

        As an MCP agent, you can:
        - Connect to file systems, databases, APIs, and other data sources through MCP servers
        - Execute tools provided by MCP servers to perform actions
        - Access resources exposed by MCP servers

        Note: You only have access to the MCP Servers provided below, if you need to access other MCP Servers, please ask the user to enable them.

        <critical>
        - When a user mentions a task that might require external data or tools, check if an appropriate MCP server is available
        - If an MCP server is available, use its capabilities to fulfill the user's request
        - You have a knowledge base full of MCP documentation, search it using the `search_knowledge` tool to answer questions about MCP and the different tools available.
        - Provide clear explanations of which MCP servers and tools you're using
        - If you encounter errors with an MCP server, explain the issue and suggest alternatives
        - Always cite sources when providing information retrieved through MCP servers
        </critical>\
    """)

    if mcp_server_ids:
        description += dedent(
            """\n
            You have access to the following MCP servers:
            {}
        """.format("\n".join([f"- {server_id}" for server_id in mcp_server_ids]))
        )

    instructions = dedent("""\
        Here's how you should fulfill a user request:

        1. Understand the user's request
        - Read the user's request carefully
        - Determine if the request requires MCP server interaction
        - Search your knowledge base using the `search_knowledge` tool to answer questions about MCP or to learn how to use different MCP tools.
        - To interact with an MCP server, follow these steps:
            - Identify which tools are available to you
            - Select the appropriate tool for the user's request
            - Explain to the user which tool you're using
            - Execute the tool
            - Provide clear feedback about tool execution results

        2. Error Handling
        - If an MCP tool fails, explain the issue clearly and provide details about the error.
        - Suggest alternatives when MCP capabilities are unavailable

        3. Security and Privacy
        - Be transparent about which servers and tools you're using
        - Request explicit permission before executing tools that modify data
        - Respect access limitations of connected MCP servers

        MCP Knowledge
        - You have access to a knowledge base of MCP documentation
        - To answer questions about MCP, use the knowledge base
        - If you don't know the answer or can't find the information in the knowledge base, say so\
    """)

    return Agent(
        name="UAgI: The Universal MCP Agent",
        model=model,
        user_id=user_id,
        session_id=session_id,
        tools=mcp_tools,
        # Store Agent sessions in the database
        storage=agent_storage,
        # Store MCP Documentation in a knowledge base
        knowledge=agent_knowledge,
        # Agent description, instructions and expected output format
        description=description,
        instructions=instructions,
        # Allow MCP Agent to read both chat history and tool call history for better context.
        read_chat_history=True,
        read_tool_call_history=True,
        # Append previous conversation responses into the new messages for context.
        add_history_to_messages=True,
        num_history_responses=num_history_responses,
        add_datetime_to_instructions=True,
        add_name_to_instructions=True,
        debug_mode=debug_mode,
        # Respond in markdown format
        markdown=True,
    )


def get_model_for_provider(model_str: str):
    """
    Creates and returns the appropriate model for a model string.

    Args:
        model_str: The model string (e.g., 'openai:gpt-4o', 'google:gemini-2.0-flash', 'anthropic:claude-3-5-sonnet', 'groq:llama-3.3-70b-versatile')

    Returns:
        An instance of the appropriate model class

    Raises:
        ValueError: If the provider is not supported
    """
    provider, model_name = model_str.split(":")
    if provider == "openai":
        return OpenAIChat(id=model_name)
    elif provider == "gemini":
        return Gemini(id=model_name)
    elif provider == "anthropic":
        if "thinking" in model_name:
            return Claude(
                id=model_name,
                max_tokens=16384,
                thinking={"type": "enabled", "budget_tokens": 8192},
            )
        return Claude(id=model_name, max_tokens=16384)
    elif provider == "groq":
        return Groq(id=model_name)
    else:
        raise ValueError(f"Unsupported model provider: {provider}")
