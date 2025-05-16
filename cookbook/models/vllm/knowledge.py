"""
python -m vllm.entrypoints.openai.api_server \
    --model microsoft/Phi-3-mini-4k-instruct \
    --dtype float32 \
    --enable-auto-tool-choice \
    --tool-call-parser pythonic          # or "json" if you prefer
"""

"""Run `pip install sqlalchemy pgvector pypdf duckduckgo-search` to install dependencies."""

from agno.agent import Agent
from agno.knowledge.pdf_url import PDFUrlKnowledgeBase
from agno.models.vllm import Vllm
from agno.vectordb.pgvector import PgVector

DB_URL = "postgresql+psycopg://ai:ai@localhost:5532/ai"

knowledge_base = PDFUrlKnowledgeBase(
    urls=["https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"],
    vector_db=PgVector(table_name="recipes", db_url=DB_URL),
)
knowledge_base.load(recreate=True)  # Comment out after first run

agent = Agent(
    model=Vllm(id="microsoft/Phi-3-mini-4k-instruct"),
    knowledge=knowledge_base,
    show_tool_calls=True,
)
agent.print_response("How to make Thai curry?", markdown=True)
