from agno.agent import Agent
from agno.knowledge.pdf_url import PDFUrlKnowledgeBase
from agno.models.openai import OpenAIChat
from agno.vectordb.pgvector import PgVector

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

knowledge_base = PDFUrlKnowledgeBase(
    urls=[
        "https://www.justice.gov/d9/criminal-ccips/legacy/2015/01/14/ccmanual_0.pdf",
    ],
    vector_db=PgVector(table_name="legal_docs", db_url=db_url),
)
knowledge_base.load(recreate=False)

legal_agent = Agent(
    name="LegalAdvisor",
    knowledge=knowledge_base,
    search_knowledge=True,
    model=OpenAIChat(id="gpt-4o"),
    markdown=True,
    instructions=[
        "Provide legal information and advice based on the knowledge base.",
        "Include relevant legal citations and sources when answering questions.",
        "Always clarify that you're providing general legal information, not professional legal advice.",
        "Recommend consulting with a licensed attorney for specific legal situations.",
    ],
)

legal_agent.print_response(
    "What are the legal consequences and criminal penalties for spoofing Email Address?",
    stream=True,
)
