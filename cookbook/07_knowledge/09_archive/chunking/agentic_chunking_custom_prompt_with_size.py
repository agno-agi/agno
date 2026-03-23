from agno.agent import Agent
from agno.knowledge.chunking.agentic import AgenticChunking
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.pdf_reader import PDFReader
from agno.vectordb.pgvector import PgVector

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

# Custom prompt with specific chunk size
custom_prompt = """
Analyze the text and break it into logical chunks.
Focus on keeping recipe instructions together as complete units.
Avoid splitting ingredient lists or cooking steps mid-sentence.
"""

knowledge = Knowledge(
    vector_db=PgVector(table_name="recipes_agentic_custom_size", db_url=db_url),
)

knowledge.insert(
    url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
    reader=PDFReader(
        name="Custom Prompt Reader with Size",
        chunking_strategy=AgenticChunking(
            max_chunk_size=2000,
            custom_prompt=custom_prompt,
        ),
    ),
)

agent = Agent(
    knowledge=knowledge,
    search_knowledge=True,
)

agent.print_response("How to make Thai curry?", markdown=True)
