"""
pip install agno
pip install fastembed, qdrant-client
pip install ollama [ollama pull qwen2.5:7b]
pip install pypdf
"""

from agno.agent import Agent
from agno.embedder.fastembed import FastEmbedEmbedder
from agno.knowledge.pdf_url import PDFUrlKnowledgeBase
from agno.models.ollama import Ollama
from agno.team import Team
from agno.vectordb.qdrant import Qdrant

collection_name = "science"
physics_tb = "https://ncert.nic.in/textbook/pdf/keph101.pdf"
chemistry_tb = "https://ncert.nic.in/textbook/pdf/lech101.pdf"

vector_db = Qdrant(
    path="/tmp/qdrant",
    collection=collection_name,
    embedder=FastEmbedEmbedder(),
)

knowledge_base = PDFUrlKnowledgeBase(
    urls=[physics_tb, chemistry_tb],
    vector_db=vector_db,
    num_documents=4,
)
knowledge_base.load()  # once the data is stored, comment this line

physics_agent = Agent(
    name="Physics Agent",
    role="Expert in Physics",
    instructions="Answer questions based on the knowledge base",
    model=Ollama(id="qwen2.5:7b"),
    read_chat_history=True,
    show_tool_calls=True,
    markdown=True,
)

chemistry_agent = Agent(
    name="Chemistry Agent",
    role="Expert in Chemistry",
    instructions="Answer questions based on the knowledge base",
    model=Ollama(id="qwen2.5:7b"),
    read_chat_history=True,
    show_tool_calls=True,
    markdown=True,
)

science_master = Team(
    name="Team with Knowledge",
    members=[physics_agent, chemistry_agent],
    model=Ollama(id="qwen2.5:7b"),
    knowledge=knowledge_base,
    search_knowledge=True,
    show_members_responses=True,
    markdown=True,
)

# science_master.print_response("give dimensional equation for volume, speed and force",stream=True)
science_master.print_response("state Henry's law", stream=True)
