from agno.agent import Agent
from agno.knowledge.pdf_url import PDFUrlKnowledgeBase
from agno.models.openai import OpenAIChat
from agno.vectordb.meilisearch import MeiliSearch, SearchType

knowledge_base = PDFUrlKnowledgeBase(
    urls=["https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"],
    vector_db=MeiliSearch(
        index_name="recipes",
        url="http://localhost:7700",
        api_key="your-api-key",  # Optional
        search_type=SearchType.hybrid,
        wait_check_task=True,
    ),
)
# Load the knowledge base: Comment out after first run
knowledge_base.load(recreate=False)

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    knowledge=knowledge_base,
    search_knowledge=True,
    read_chat_history=True,
    show_tool_calls=True,
    markdown=True,
)
agent.print_response(
    "How do I make chicken and galangal in coconut milk soup", stream=True
)
agent.print_response("What was my last question?", stream=True)
