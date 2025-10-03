from agno.agent import Agent
from agno.knowledge.pdf_url import PDFUrlKnowledgeBase
from agno.vectordb.opensearch import OpensearchDb

vector_db = OpensearchDb(
    index_name="recipe",
    dimension=1536,
    hosts=[
        {
            "host": "localhost",
            "port": 9200,
        }
    ],
    # Uncomment the following line to use basic authentication
    # http_auth=("username", "password"),
)
knowledge_base = PDFUrlKnowledgeBase(
    urls=["https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"],
    vector_db=vector_db,
)
knowledge_base.load(recreate=False)  # Comment out after first run

agent = Agent(knowledge=knowledge_base, show_tool_calls=True)
agent.print_response("How to make Thai curry?", markdown=True)
