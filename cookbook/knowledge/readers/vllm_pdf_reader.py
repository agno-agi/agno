from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.vllm_pdf_reader import VllmPDFReader
from agno.models.openai import OpenAIChat
from agno.vectordb.pgvector import PgVector

model_embeddings = "text-embedding-3-small"
model_name = "gpt-4o"
data_path = "path/to/your/knowledge/base"

table_name = "your-table-name"

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

embedder = OpenAIEmbedder(id=model_embeddings)

vllm = OpenAIChat(id=model_name)

knowledge = Knowledge(
    vector_db=PgVector(
        embedder=embedder,
        table_name=table_name,
        db_url=db_url,
    )
)

knowledge.vector_db.create()

knowledge.add_content(
    path=data_path,
    reader=VllmPDFReader(vllm=vllm),
)

agent = Agent(
    model=vllm,
    knowledge=knowledge,
    search_knowledge=True,
)

agent.print_response(
    "Based on the block diagram, how does the signal flow through the PID controller board, and what role does each processing stage play ?",
    markdown=True,
)
