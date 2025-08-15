from agno.agent import Agent
from agno.knowledge.pdf_url import PDFUrlKnowledgeBase
from agno.models.openai import OpenAIChat
from agno.vectordb.opensearch import OpensearchDb
from agno.vectordb.search import SearchType

knowledge_base = PDFUrlKnowledgeBase(
    urls=["https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"],
    vector_db=OpensearchDb(
        index_name="recipe",
        dimension=1536,
        search_type=SearchType.hybrid,
        hosts=[
            {
                "host": "localhost",
                "port": 9200,
            }
        ],
        # Uncomment the following line to use basic authentication
        # http_auth=("username", "password"),
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
