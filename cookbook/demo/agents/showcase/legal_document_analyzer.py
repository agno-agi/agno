"""Legal Document Analyzer - AI agent with legal knowledge base for document analysis and contract review"""

from textwrap import dedent

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.anthropic import Claude
from agno.vectordb.lancedb import LanceDb, SearchType
from pydantic import BaseModel, Field

from shared.database import db


class LegalAnalysis(BaseModel):
    """Structured legal document analysis"""

    document_type: str = Field(description="Type of legal document")
    key_clauses: list[str] = Field(description="Important clauses identified")
    potential_issues: list[str] = Field(description="Potential legal concerns or red flags")
    recommendations: list[str] = Field(description="Recommended actions or modifications")
    risk_score: float = Field(description="Risk score from 0.0 (low) to 10.0 (high)")
    summary: str = Field(description="Plain-language summary of the document")


# Create legal knowledge base with LanceDB
legal_knowledge = Knowledge(
    contents_db=db,
    vector_db=LanceDb(
        uri="tmp/lancedb",
        table_name="legal_docs",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small", dimensions=1536),
    ),
)

legal_analyzer = Agent(
    id="legal-document-analyzer",
    name="Legal Document Analyzer",
    session_id="legal_analyzer_session",
    model=Claude(id="claude-sonnet-4-20250514"),
    knowledge=legal_knowledge,
    db=db,
    description=dedent("""\
        AI legal assistant specializing in document analysis, contract review,
        and legal research. Uses RAG to reference legal precedents and best practices.
        Remembers your document preferences, past reviews, and common clauses.
        Note: This is for educational purposes only, not a substitute for professional legal advice.\
    """),
    instructions=[
        "Analyze legal documents thoroughly using your knowledge base",
        "Identify key clauses, terms, and obligations",
        "Flag potential issues, ambiguities, or unfavorable terms",
        "Explain legal jargon in plain language",
        "Compare against standard legal practices and precedents",
        "Provide risk assessment and recommendations",
        "Highlight areas requiring professional legal review",
        "Search your knowledge base for relevant legal information",
        "Remember client preferences and past document reviews",
        "Track common clauses and terms across documents",
        "Reference similar past documents for comparison",
        "Always include disclaimer about seeking professional legal counsel",
    ],
    enable_user_memories=True,
    enable_session_summaries=True,
    add_history_to_context=True,
    num_history_runs=10,
    add_datetime_to_context=True,
    output_schema=LegalAnalysis,
    markdown=True,
)


async def load_legal_knowledge():
    """Load legal resources into the knowledge base"""
    try:
        print("\n📚 Loading legal resources into knowledge base...")
        # Example: Load from legal information sources
        # In production, you would load from your legal document library
        await legal_knowledge.add_content_async(
            name="Legal Basics",
            url="https://www.law.cornell.edu/wex",
            skip_if_exists=True,
        )
        print("✅ Legal knowledge base loaded successfully")
    except Exception as e:
        print(f"⚠️  Warning: Could not load legal knowledge base: {e}")
