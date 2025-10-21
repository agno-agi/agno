from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.pptx_reader import PPTXReader
from agno.models.openai import OpenAIChat
from agno.vectordb.pgvector import PgVector

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

# Create a knowledge base with PPTX documents
knowledge = Knowledge(
    # Table name: ai.pptx_documents
    vector_db=PgVector(
        table_name="pptx_documents",
        db_url=db_url,
    ),
)

# Load PPTX content from file(s)
# You can load multiple PPTX files by calling add_content multiple times
knowledge.add_content(
    path="path/to/your/presentation.pptx",  # Replace with actual PPTX file path
    reader=PPTXReader(),
)

# Create an agent with the knowledge
agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    knowledge=knowledge,
    search_knowledge=True,
)

# Ask the agent about the knowledge
agent.print_response(
    "Search through the presentation content and tell me what key topics, main points, or information are covered in the slides. Be specific about what you find in the knowledge base.",
    markdown=True,
)
