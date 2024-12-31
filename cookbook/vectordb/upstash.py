# install upstash-vector - `pip install upstash-vector`

from phi.agent import Agent
from phi.knowledge.pdf import PDFUrlKnowledgeBase
from phi.vectordb.upstash import Upstash
from phi.embedder.openai import OpenAIEmbedder

# OPENAI_API_KEY must be set in the environment
VECTOR_DB_DIMENSION = 1536

# Initialize Upstash DB
vector_db = Upstash(
    url="UPSTASH_VECTOR_REST_URL", 
    token="UPSTASH_VECTOR_REST_TOKEN",
    dimension=VECTOR_DB_DIMENSION,
    embedder=OpenAIEmbedder(dimensions=VECTOR_DB_DIMENSION),
)

# Create a new PDFUrlKnowledgeBase
knowledge_base = PDFUrlKnowledgeBase(
    urls=["https://phi-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"],
    vector_db=vector_db,
)

knowledge_base.load(recreate=False, upsert=True)  # Comment out after first run

# Create and use the agent
agent = Agent(knowledge_base=knowledge_base, use_tools=True, show_tool_calls=True)
agent.print_response("What are some tips for cooking glass noodles?", markdown=True)