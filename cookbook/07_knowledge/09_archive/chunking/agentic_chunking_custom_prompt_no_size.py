from agno.agent import Agent
from agno.knowledge.chunking.agentic import AgenticChunking
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.pdf_reader import PDFReader
from agno.vectordb.pgvector import PgVector

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

# Custom prompt without chunk size will use default chunk size.
custom_prompt = """
Analyze the text and break it into logical sections.
Each section should contain complete recipes with all ingredients and instructions.
Prioritize keeping related information together.
"""

knowledge = Knowledge(
    vector_db=PgVector(table_name="recipes_agentic_custom_no_size", db_url=db_url),
)

knowledge.insert(
    url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
    reader=PDFReader(
        name="Custom Prompt Reader without Size",
        chunking_strategy=AgenticChunking(
            custom_prompt=custom_prompt,
        ),
    ),
)

agent = Agent(
    knowledge=knowledge,
    search_knowledge=True,
)

agent.print_response("How to make Thai curry?", markdown=True)
