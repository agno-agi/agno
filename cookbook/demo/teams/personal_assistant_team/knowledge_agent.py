from textwrap import dedent

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIChat
from agno.vectordb.pgvector import PgVector

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

vector_db = PgVector(table_name="assistant_knowledge", db_url=db_url)

knowledge_base = Knowledge(
    vector_db=vector_db,
)

knowledge_agent = Agent(
    name="Knowledge Agent",
    model=OpenAIChat(id="gpt-4o"),
    instructions=dedent("""
    You are a knowledge agent that can answer questions about the knowledge base.
    Always use the knowledge base to answer questions.
    If the user asks a question that is not in the knowledge base, you should say that you don't know the answer.
    If the user instructs you to update the knowledge base, you should update the knowledge base with the information provided by the user.
    """),
    knowledge=knowledge_base,
    search_knowledge=True,
    update_knowledge=True,
    add_history_to_context=True,
    add_datetime_to_context=True,
    markdown=True,
    debug_mode=True,
)
