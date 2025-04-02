"""Agent with Storage - An agent that can store sessions in a database

Install dependencies: `pip install openai lancedb tantivy sqlalchemy agno`
"""

from pathlib import Path
from textwrap import dedent

from agno.agent import Agent
from agno.embedder.openai import OpenAIEmbedder
from agno.knowledge.url import UrlKnowledge
from agno.models.openai import OpenAIChat
from agno.storage.sqlite import SqliteStorage
from agno.vectordb.lancedb import LanceDb, SearchType

# Setup paths
cwd = Path(__file__).parent
tmp_dir = cwd.joinpath("tmp")
tmp_dir.mkdir(parents=True, exist_ok=True)

# Initialize knowledge & storage
agent_knowledge = UrlKnowledge(
    urls=["https://docs.agno.com/llms-full.txt"],
    vector_db=LanceDb(
        uri=str(tmp_dir.joinpath("lancedb")),
        table_name="agno_assist_knowledge",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)
agent_storage = SqliteStorage(
    table_name="agno_assist_sessions",
    db_file=str(tmp_dir.joinpath("agent_sessions.db")),
)

agent_with_storage = Agent(
    name="Agent with Storage",
    model=OpenAIChat(id="gpt-4o"),
    description=dedent("""\
    You are AgnoAssist, an AI Agent specializing in Agno: A lighweight python framework for building multimodal agents.
    Your goal is to help developers understand and effectively use Agno by providing
    explanations and working code examples"""),
    instructions=dedent("""\
    Your mission is to provide comprehensive support for Agno developers. Follow these steps to ensure the best possible response:

    1. **Analyze the request**
        - Analyze the request to determine if it requires a knowledge search, creating an Agent, or both.
        - If you need to search the knowledge base, identify 1-3 key search terms related to Agno concepts.
        - If you need to create an Agent, search the knowledge base for relevant concepts and use the example code as a guide.
        - When the user asks for an Agent, they mean an Agno Agent.
        - All concepts are related to Agno, so you can search the knowledge base for relevant information

    After Analysis, always start the iterative search process. No need to wait for approval from the user.

    2. **Iterative Search Process**:
        - Use the `search_knowledge_base` tool to search for related concepts, code examples and implementation details
        - Continue searching until you have found all the information you need or you have exhausted all the search terms

    After the iterative search process, determine if you need to create an Agent.
    If you do, generate a code example that the user can run.

    3. **Code Creation**
        - Create complete, working code examples that users can run. For example:
        ```python
        from agno.agent import Agent
        from agno.tools.duckduckgo import DuckDuckGoTools

        agent = Agent(tools=[DuckDuckGoTools()])

        # Perform a web search and capture the response
        response = agent.run("What's happening in France?")
        ```
        - Remember to:
            * Build the complete agent implementation.
            * Include all necessary imports and setup.
            * Add comprehensive comments explaining the implementation
            * Test the agent with example queries
            * Ensure all dependencies are listed
            * Include error handling and best practices
            * Add type hints and documentation

    Key topics to cover:
    - Agent levels and capabilities
    - Knowledge base and memory management
    - Tool integration
    - Model support and configuration
    - Best practices and common patterns"""),
    knowledge=agent_knowledge,
    storage=agent_storage,
    show_tool_calls=True,
    # To provide the agent with the chat history
    # We can either:
    # 1. Provide the agent with a tool to read the chat history
    # 2. Automatically add the chat history to the messages sent to the model
    #
    # 1. Provide the agent with a tool to read the chat history
    read_chat_history=True,
    # 2. Automatically add the chat history to the messages sent to the model
    add_history_to_messages=True,
    # Number of historical runs to add to the messages.
    num_history_responses=3,
    markdown=True,
)

if __name__ == "__main__":
    # Set to False after the knowledge base is loaded
    load_knowledge = True
    if load_knowledge:
        agent_knowledge.load()

    agent_with_storage.print_response("Tell me about the Agno framework", stream=True)
    agent_with_storage.print_response("What was my last question?", stream=True)
