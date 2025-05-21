from textwrap import dedent

from agno.agent import Agent
from agno.embedder.openai import OpenAIEmbedder
from agno.knowledge.url import UrlKnowledge
from agno.memory.v2.db.sqlite import SqliteMemoryDb
from agno.memory.v2.memory import Memory
from agno.models.anthropic import Claude
from agno.models.openai import OpenAIChat
from agno.reranker.cohere import CohereReranker
from agno.storage.sqlite import SqliteStorage
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.python import PythonTools
from agno.tools.reasoning import ReasoningTools
from agno.vectordb.lancedb import LanceDb, SearchType

# You can also use `https://docs.agno.com/llms-full.txt` for the full documentation
knowledge_base = UrlKnowledge(
    urls=["https://docs.agno.com/introduction.md"],
    vector_db=LanceDb(
        uri="tmp/lancedb",
        table_name="agno_docs",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
        reranker=CohereReranker(model="rerank-multilingual-v3.0"),
    ),
)

memory = Memory(
    # Use any model for creating memories
    model=OpenAIChat(id="gpt-4.1"),
    db=SqliteMemoryDb(table_name="user_memories", db_file="tmp/agent.db"),
    delete_memories=True,
    clear_memories=True,
)

storage = SqliteStorage(table_name="agent_sessions", db_file="tmp/agent.db")

agno_assist = Agent(
    name="Agno AGI",
    model=Claude(id="claude-3-7-sonnet-latest"),
    # User for the memories
    user_id="ava",
    description=dedent("""\
    You are `Agno AGI`, an autonomous AI Agent that can build other agents using the Agno framework.
    Your goal is to help developers understand and use Agno by providing explanations,
    working code examples, and optional visual and audio explanations of key concepts.
    """),
    instructions=dedent("""\
    1. **Analyze the request**
        - Analyze the request to determine if it requires a knowledge search, creating an Agent, or both.
        - If you need to search the knowledge base, identify 1-3 key search terms related to Agno concepts.
        - If you need to create an Agent, search the knowledge base for relevant concepts and use the example code as a guide.
        - All concepts are related to Agno, so you can search the knowledge base for relevant information

    After Analysis, start the iterative search process. No need to wait for approval from the user.

    2. **Iterative Search Process**:
        - Use the `search_knowledge_base` tool to search for related concepts, code examples and implementation details
        - Continue searching until you have found all the information you need or you have exhausted all the search terms

    After the iterative search process, determine if you need to create an Agent.
    If you do, ask the user if they want you to create the Agent and run it.

    3. **Code Creation**
        - Create complete, working code examples that users can run.
        - You must remember to use agent.run() and NOT agent.print_response()
        - This way you can capture the response and return it to the user
        - Remember to:
            * Build the complete agent implementation
            * Include all necessary imports and setup
            * Add comprehensive comments explaining the implementation
            * Test the agent with example queries
            * Ensure all dependencies are listed
            * Include error handling and best practices
            * Add type hints and documentation\
    """),
    tools=[PythonTools(), DuckDuckGoTools(), ReasoningTools(add_instructions=True)],
    add_datetime_to_instructions=True,
    # Agentic RAG is enabled by default when `knowledge` is provided to the Agent.
    knowledge=knowledge_base,
    # Store Agent sessions in a sqlite database
    storage=storage,
    # Add the chat history to the messages
    add_history_to_messages=True,
    # Number of history runs
    num_history_runs=3,
    # Store memories in a sqlite database
    memory=memory,
    # Let the Agent manage its memories
    enable_agentic_memory=True,
    markdown=True,
)

if __name__ == "__main__":
    # Load the knowledge base, comment after first run
    # agno_assist.knowledge.load(recreate=True)
    # You can comment this out after the first run and the agent will remember the instructions
    # agno_assist.print_response("My name is Ava and you should always start your messages with 'hi ava'", stream=True)
    agno_assist.print_response("What is Agno?", stream=True)
