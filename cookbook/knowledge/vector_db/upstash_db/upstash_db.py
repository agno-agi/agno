# install upstash-vector - `uv pip install upstash-vector`
# Add OPENAI_API_KEY to your environment variables for the agent response

import os

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.upstashdb import UpstashVectorDb

# How to connect to an Upstash Vector index
# - Create a new index in Upstash Console with the correct dimension
# - Fetch the URL and token from Upstash Console
# - Replace the values below or use environment variables

vector_db = UpstashVectorDb(
    url=os.getenv("UPSTASH_VECTOR_REST_URL"),
    token=os.getenv("UPSTASH_VECTOR_REST_TOKEN"),
)

# Initialize Upstash DB
knowledge = Knowledge(
    name="Basic SDK Knowledge Base",
    description="Agno 2.0 Knowledge Implementation with Upstash Vector DB",
    vector_db=vector_db,
)

# Add content with metadata
knowledge.add_content(
    name="Recipes",
    url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
    metadata={"doc_type": "recipe_book"},
)

# Create and use the agent
agent = Agent(knowledge=knowledge)
agent.print_response("How to make Pad Thai?", markdown=True)


vector_db.delete_by_name("Recipes")
# or
vector_db.delete_by_metadata({"doc_type": "recipe_book"})
