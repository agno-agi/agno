"""Run `pip install ddgs sqlalchemy pgvector pypdf anthropic openai` to install dependencies."""

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.vertexai.claude import Claude
from agno.vectordb.pgvector import PgVector

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

knowledge = Knowledge(
    vector_db=PgVector(
        table_name="recipes",
        db_url=db_url,
        embedder=OpenAIEmbedder(),
    ),
)
# Add content to the knowledge
knowledge.add_content(
    url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"
)

agent = Agent(
    model=Claude(id="claude-sonnet-4@20250514"),
    knowledge=knowledge,
)
agent.print_response("How to make Thai curry?", markdown=True)
