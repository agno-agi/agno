import logging
from agno.agent import Agent
from agno.knowledge.pdf_url import PDFUrlKnowledgeBase
from agno.models.litellm import LiteLLM
from agno.vectordb.pgvector import PgVector

# Setup logging (great for hackathon debugging/demoing)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Database URL
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

# Vector DB config
vector_db = PgVector(table_name="recipes", db_url=db_url)

# Load knowledge base from Thai Recipes PDF
knowledge_base = PDFUrlKnowledgeBase(
    urls=["https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"],
    vector_db=vector_db,
)

# Load PDF and embed content into DB — only once!
try:
    logger.info("Loading knowledge base...")
    knowledge_base.load(recreate=False)  # Change to True if reloading is needed
    logger.info("Knowledge base loaded successfully.")
except Exception as e:
    logger.error(f"Failed to load knowledge base: {e}")

# Configure the Agent
agent = Agent(
    model=LiteLLM(id="gpt-4o"),
    knowledge=knowledge_base,
    show_tool_calls=True,  # Show vector search/tool context
)

# Query the AI — Markdown beautified
query = "How do I make Thai curry?"
logger.info(f"Querying agent: {query}")
response = agent.get_response(query, markdown=True)

print("### 🍛 Thai Curry Recipe")
print(response.content)
