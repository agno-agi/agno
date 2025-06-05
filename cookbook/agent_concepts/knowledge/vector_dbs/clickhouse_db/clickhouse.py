from agno.agent import Agent
from agno.knowledge.pdf_url import PDFUrlKnowledgeBase
from agno.storage.agent.sqlite import SqliteAgentStorage
from agno.vectordb.clickhouse import Clickhouse

agent = Agent(
    storage=SqliteAgentStorage(table_name="recipe_agent"),
    knowledge=PDFUrlKnowledgeBase(
        urls=["https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"],
        vector_db=Clickhouse(
            table_name="recipe_documents",
            host="localhost",
            port=8123,
            username="ai",
            password="ai",
        ),
    ),
    # Show tool calls in the response
    show_tool_calls=True,
    # Enable the agent to search the knowledge base
    search_knowledge=True,
    # Enable the agent to read the chat history
    read_chat_history=True,
)
# Comment out after first run
agent.knowledge.load(recreate=False)  # type: ignore

agent.print_response("How do I make pad thai?", markdown=True)
