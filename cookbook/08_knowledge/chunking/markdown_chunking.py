from agno.agent import Agent
from agno.knowledge.chunking.markdown import MarkdownChunking
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.markdown_reader import MarkdownReader
from agno.vectordb.pgvector import PgVector

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

knowledge = Knowledge(
    vector_db=PgVector(table_name="recipes_md_chunking", db_url=db_url),
)

knowledge.add_content(
    url="https://raw.githubusercontent.com/agno-agi/agno/main/README.md",
    reader=MarkdownReader(
        name="MD Chunking Reader",
        chunking_strategy=MarkdownChunking(),
    ),
)

agent = Agent(
    knowledge=knowledge,
    search_knowledge=True,
)

agent.print_response("What can you tell me about Agno?", markdown=True)
