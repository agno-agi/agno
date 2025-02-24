# install upstash-vector - `uv pip install upstash-vector`
# Add OPENAI_API_KEY to your environment variables for the agent response

from agno.agent import Agent
from agno.knowledge.pdf_url import PDFUrlKnowledgeBase
from agno.vectordb.upstashdb.upstashdb import UpstashVectorDb

# How to connect to an Upstash Vector index
# - Create a new index in Upstash Console with the correct dimension
# - Fetch the URL and token from Upstash Console
# - Replace the values below or use environment variables

# Initialize Upstash DB
vector_db = UpstashVectorDb(
    url="UPSTASH_VECTOR_REST_URL",
    token="UPSTASH_VECTOR_REST_TOKEN",
)

# Create a new PDFUrlKnowledgeBase
knowledge_base = PDFUrlKnowledgeBase(
    urls=["https://phi-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"],
    vector_db=vector_db,
)

# Load the knowledge base - after first run, comment out
knowledge_base.load(recreate=False, upsert=True)

# Create and use the agent
agent = Agent(knowledge=knowledge_base, show_tool_calls=True)
agent.print_response("What are some tips for cooking glass noodles?", markdown=True)
