from agno.agent import Agent
from agno.knowledge.chunking.semantic import SemanticChunking
from agno.knowledge.embedder.google import GeminiEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.pdf_reader import PDFReader
from agno.vectordb.pgvector import PgVector
from chonkie.embeddings import GeminiEmbeddings

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

agno_embedder = (
    GeminiEmbedder()
)  # Agno embedder is used to get the embedding for the vector database
chonkie_embedder = GeminiEmbeddings(
    model="gemini-embedding-exp-03-07"
)  # Chonkie embedder is used to get the embedding for the semantic chunking

knowledge = Knowledge(
    vector_db=PgVector(
        table_name="recipes_semantic_chunking", db_url=db_url, embedder=agno_embedder
    ),
)
knowledge.add_content(
    url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
    reader=PDFReader(
        name="Semantic Chunking Reader",
        chunking_strategy=SemanticChunking(
            embedder=chonkie_embedder,
            chunk_size=500,
            similarity_threshold=0.5,
            similarity_window=3,
            min_sentences_per_chunk=1,
            min_characters_per_sentence=24,
            delimiters=[". ", "! ", "? ", "\n"],
            include_delimiters="prev",
            skip_window=0,
            filter_window=5,
            filter_polyorder=3,
            filter_tolerance=0.2,
        ),
    ),
)

agent = Agent(
    knowledge=knowledge,
    search_knowledge=True,
)

agent.print_response("How to make Thai curry?", markdown=True)
