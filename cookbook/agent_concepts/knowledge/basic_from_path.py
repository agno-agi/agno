from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.pgvector import PgVector

# Create Knowledge Instance
knowledge = Knowledge(
    name="Basic SDK Knowledge Base",
    description="Agno 2.0 Knowledge Implementation",
    vector_store=PgVector(
        table_name="vectors", db_url="postgresql+psycopg://ai:ai@localhost:5532/ai"
    ),
)

# Add from URL to the knowledge base
knowledge.add_content(
    name="Recipes",
    url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
    metadata={"user_tag": "Recipes from website"},
)

# Add from local file to the knowledge base
knowledge.add_content(
    name="CV",
    path="cookbook/agent_concepts/knowledge/testing_resources/",
    metadata={"user_tag": "Engineering Candidates"},
)

agent = Agent(
    name="My Agent",
    description="Agno 2.0 Agent Implementation",
    knowledge=knowledge,
    search_knowledge=True,
    debug_mode=True,
)

agent.print_response(
    "What can you tell me about Thai recipes?",
    markdown=True,
)

agent.print_response(
    "Which candidates can you recommend for the role of a software engineer?",
    markdown=True,
)

knowledge.remove_vector_by_name("CV")

knowledge.remove_vector_by_metadata({"user_tag": "Engineering Candidates"})
