from textwrap import dedent
from typing import List, Optional

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.tools.mcp import MCPTools
from agno.utils.streamlit import get_model_from_id
from agno.vectordb.pgvector import PgVector

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"


def get_mcp_agent(
    model_id: str = "openai:gpt-4o",
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    mcp_tools: Optional[List[MCPTools]] = None,
    mcp_server_ids: Optional[List[str]] = None,
) -> Agent:
    """Get a Universal MCP Agent."""

    # Database for sessions
    db = PostgresDb(
        db_url=db_url,
        session_table="sessions",
        db_schema="ai",
    )

    # Knowledge base for MCP documentation
    contents_db = PostgresDb(
        db_url=db_url,
        knowledge_table="mcp_agent_knowledge_contents",
        db_schema="ai",
    )

    knowledge_base = Knowledge(
        name="MCP Agent Knowledge Base",
        description="Knowledge base for MCP documentation and usage",
        vector_db=PgVector(
            db_url=db_url,
            table_name="mcp_agent_documents",
            schema="ai",
            embedder=OpenAIEmbedder(id="text-embedding-3-small"),
        ),
        contents_db=contents_db,
        max_results=3,
    )

    try:
        knowledge_base.add_content(
            url="https://modelcontextprotocol.io/llms-full.txt",
            name="MCP Documentation",
            description="Complete Model Context Protocol documentation",
        )
    except Exception:
        # Documentation might already be added
        pass

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
        - You have a knowledge base full of MCP documentation, search it using the `search_knowledge_base` tool to answer questions about MCP and the different tools available.
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
        - Search your knowledge base using the `search_knowledge_base` tool to answer questions about MCP or to learn how to use different MCP tools.
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

    agent = Agent(
        name="UAgI: The Universal MCP Agent",
        model=get_model_from_id(model_id),
        id="universal-mcp-agent",
        user_id=user_id,
        session_id=session_id,
        db=db,
        knowledge=knowledge_base,
        tools=mcp_tools,
        add_history_to_context=True,
        num_history_runs=5,
        read_chat_history=True,
        read_tool_call_history=True,
        add_datetime_to_context=True,
        add_name_to_context=True,
        description=description,
        instructions=instructions,
        markdown=True,
        debug_mode=True,
    )

    return agent
