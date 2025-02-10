"""
Run `pip install duckduckgo-search sqlalchemy pgvector pypdf openai ollama` to install dependencies.

Run Ollama Server: `ollama serve`
Pull required models:
`ollama pull nomic-embed-text`
`ollama pull llama3.1:8b`

If you haven't deployed database yet, run:
`docker run --rm -it -e POSTGRES_PASSWORD=ai -e POSTGRES_USER=ai -e POSTGRES_DB=ai -p 5532:5432 --name postgres pgvector/pgvector:pg17`
to deploy a PostgreSQL database.

"""

from agno.agent import Agent
from agno.embedder.ollama import OllamaEmbedder
from agno.knowledge.pdf_url import PDFUrlKnowledgeBase
from agno.models.ollama import OllamaTools
from agno.vectordb.pgvector import PgVector

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

knowledge_base = PDFUrlKnowledgeBase(
    urls=["https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"],
    vector_db=PgVector(
        table_name="ollama_recipes",
        db_url=db_url,
        embedder=OllamaEmbedder(id="nomic-embed-text", dimensions=768),
    ),
)
knowledge_base.load(recreate=False)  # Comment out after first run

agent = Agent(
    model=OllamaTools(id="llama3.1:8b"),
    knowledge=knowledge_base,
    show_tool_calls=True,
)
agent.print_response("How to make Thai curry?", markdown=True)
