import os
from typing import Optional

import nltk  # type: ignore
import typer
from agno.agent import Agent
from agno.knowledge.pdf_url import PDFUrlKnowledgeBase
from agno.vectordb.pineconedb import PineconeDb
from rich.prompt import Prompt

nltk.download("punkt")
nltk.download("punkt_tab")

api_key = os.getenv("PINECONE_API_KEY")
index_name = "thai-recipe-hybrid-search"

vector_db = PineconeDb(
    name=index_name,
    dimension=1536,
    metric="cosine",
    spec={"serverless": {"cloud": "aws", "region": "us-east-1"}},
    api_key=api_key,
    use_hybrid_search=True,
    hybrid_alpha=0.5,
)

knowledge_base = PDFUrlKnowledgeBase(
    urls=["https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"],
    vector_db=vector_db,
)


def pinecone_agent(user: str = "user"):
    agent = Agent(
        user_id=user,
        knowledge=knowledge_base,
        search_knowledge=True,
        show_tool_calls=True,
    )

    while True:
        message = Prompt.ask(f"[bold] :sunglasses: {user} [/bold]")
        if message in ("exit", "bye"):
            break
        agent.print_response(message)


if __name__ == "__main__":
    # Comment out after first run
    knowledge_base.load(recreate=False, upsert=True)

    typer.run(pinecone_agent)
