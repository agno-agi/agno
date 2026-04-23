"""
Moss: High-Performance Semantic Search
=======================================
Moss manages embeddings internally and serves queries from an in-memory
runtime, delivering sub-10ms latency with no external embedder required.

Setup:
    pip install inferedge-moss

Environment variables:
    MOSS_PROJECT_ID   - Your Moss project ID
    MOSS_PROJECT_KEY  - Your Moss project key

Or pass project_id / project_key directly to MossVectorDb.

See also: 01_qdrant.py for a feature-rich production option.
"""

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIResponses
from agno.vectordb.moss import MossVectorDb

if __name__ == "__main__":
    # No embedder needed — Moss handles embeddings internally.
    # knowledge.insert() creates + loads the index on first call;
    # every search() after that hits Moss's in-memory runtime.
    knowledge = Knowledge(
        vector_db=MossVectorDb(
            index_name="thai-recipes",
            # project_id and project_key fall back to MOSS_PROJECT_ID / MOSS_PROJECT_KEY
            embedding_model="moss-minilm",  # or "moss-mediumlm" for higher accuracy
            alpha=0.8,  # 1.0 = pure semantic, 0.0 = pure keyword
        ),
    )

    agent = Agent(
        model=OpenAIResponses(id="gpt-5.4"),
        knowledge=knowledge,
        search_knowledge=True,
        markdown=True,
    )

    print("Moss: Basic hybrid search")

    # Ingest content — creates the index if it doesn't exist, then loads it.
    knowledge.insert(url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf")

    agent.print_response("What Thai recipes do you know?", stream=True)
