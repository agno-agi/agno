from agno.agent import Agent
from agno.knowledge.chunking.markdown import MarkdownChunking
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.markdown_reader import MarkdownReader
from agno.vectordb.chroma import ChromaDb

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

knowledge = Knowledge(
    vector_db=ChromaDb(collection="recipes_md_chunking", path="tmp/chromadb"),
)

knowledge.add_content(
    url="https://github.com/agno-agi/agno/blob/main/README.md",
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
