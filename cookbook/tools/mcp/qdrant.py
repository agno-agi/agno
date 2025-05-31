# pip install agno google-genai mcp 
# Inside .env: GOOGLE_API_KEY = AI*****

import asyncio
import sys
from agno.agent import Agent
from agno.models.google import Gemini
from agno.tools.mcp import MCPTools
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client

QDRANT_URL = "<replace_with_your_qdrant_url>"
QDRANT_API_KEY = "<replace_with_your_qdrant_api_key>"
COLLECTION_NAME = "vibe-code"
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

async def create_mcp_agent(session):
    """Create and configure Qdrant MCP Server"""
    mcp_tools = MCPTools(session=session)
    await mcp_tools.initialize()
    
    return Agent(
        model=Gemini(id="gemini-2.5-flash-preview-05-20"),
        tools=[mcp_tools],
        instructions="""
        You are the storage agent for the Model Context Protocol (MCP) server.
        You need to save the files in the vector database and answer the user's questions.
        You can use the following tools:
        - qdrant-store: Store data/output in the Qdrant vector database.
        - qdrant-find: Retrieve data/output from the Qdrant vector database.
        """,
        markdown=True,
        show_tool_calls=True,
    )

async def run_agent(message:str) -> None:
    server_params = StdioServerParameters(
        command = "uvx",
        args = ["mcp-server-qdrant"],
        env = {
            "QDRANT_URL": QDRANT_URL,
            "QDRANT_API_KEY": QDRANT_API_KEY,
            "COLLECTION_NAME": COLLECTION_NAME,
            "EMBEDDING_MODEL": EMBEDDING_MODEL
        }
    )

    try:
        async with stdio_client(server_params) as (read,write):
            async with ClientSession(read,write) as session:
                agent = await create_mcp_agent(session)
                await agent.aprint_response(message,stream=True)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
        raise
    finally:
        await asyncio.sleep(0.1)

if __name__ == "__main__":
    query = """
    write a pytorch code for CNN,
    I need 3 conv layer with 32, 64, 128 filters and 2 fully connected layer with 512, 256 neurons along with dropout layer of 0.3. 
    Save the code in the vector database
    """
    try:
        asyncio.run(run_agent(query))
    except KeyboardInterrupt:
        print("\nShutting down...")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
