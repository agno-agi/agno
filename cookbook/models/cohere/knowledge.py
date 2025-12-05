"""Run `pip install ddgs sqlalchemy pgvector pypdf openai cohere` to install dependencies."""

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.models.cohere import Cohere
from agno.vectordb.pgvector import PgVector

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

knowledge = Knowledge(
    vector_db=PgVector(table_name="recipes", db_url=db_url),
)
# Add content to the knowledge
knowledge.add_content(
    url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"
)

agent = Agent(model=Cohere(id="command-a-03-2025"), knowledge=knowledge)
agent.print_response("How to make Thai curry?", markdown=True)
