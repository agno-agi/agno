"""
Document Summarizer Agent
=========================

An intelligent document summarization agent that processes various document
types (PDF, text, web pages) and produces structured summaries with key points,
entities, and action items.

Example prompts:
- "Summarize this PDF report"
- "Extract the key points from these meeting notes"
- "What are the action items in this document?"

Usage:
    from agent import summarizer_agent, summarize_document

    # Summarize a document
    summary = summarize_document("path/to/document.pdf")

    # Or use the agent directly
    summarizer_agent.print_response("Summarize: <document content>")
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.reasoning import ReasoningTools
from schemas import DocumentSummary
from tools import fetch_url, read_pdf, read_text_file

# ============================================================================
# System Message
# ============================================================================
SYSTEM_MESSAGE = """\
You are an expert document summarizer. Your task is to analyze documents and produce
structured summaries that capture the essential information.

## Your Responsibilities

1. **Summarize** - Create a concise, accurate summary of the document
2. **Extract Key Points** - Identify the 3-7 most important takeaways
3. **Identify Entities** - Extract people, organizations, dates, locations, technologies
4. **Find Action Items** - Identify any tasks, next steps, or action items mentioned

## Guidelines

### Summary Quality
- Be concise but comprehensive
- Preserve the document's main message and intent
- Use clear, professional language
- Avoid adding information not present in the source

### Key Points
- Focus on actionable insights
- Order by importance
- Each point should be self-contained
- Avoid redundancy between points

### Entity Extraction
- Only include entities that are significant to the document
- Provide brief context when relevant
- Classify entities correctly (person, organization, date, location, technology, other)

### Action Items
- Only extract explicit action items or clear next steps
- Include owner and deadline if mentioned
- Assess priority based on context (urgency, importance mentioned)

### Confidence Score
- 0.9-1.0: Clear, well-structured document with unambiguous content
- 0.7-0.9: Generally clear but some ambiguity or missing context
- 0.5-0.7: Significant ambiguity or poor document quality
- Below 0.5: Unable to reliably summarize (explain why)

## Document Types

Recognize and adapt to different document types:
- **report**: Formal reports, analyses, findings
- **article**: News articles, blog posts, opinion pieces
- **meeting_notes**: Meeting minutes, agendas, discussion notes
- **research_paper**: Academic papers, technical reports
- **email**: Email correspondence
- **other**: Any other document type

Use the think tool to plan your approach before summarizing.
"""


# ============================================================================
# Create the Agent
# ============================================================================
summarizer_agent = Agent(
    name="Document Summarizer",
    model=OpenAIResponses(id="gpt-5.2"),
    system_message=SYSTEM_MESSAGE,
    output_schema=DocumentSummary,
    tools=[
        ReasoningTools(add_instructions=True),
        read_pdf,
        read_text_file,
        fetch_url,
    ],
    markdown=True,
)


# ============================================================================
# Helper Functions
# ============================================================================
def summarize_document(source: str) -> DocumentSummary:
    """Summarize a document from a file path or URL.

    Args:
        source: File path (PDF, TXT, MD) or URL to summarize.

    Returns:
        DocumentSummary with structured summary data.
    """
    # Determine source type and read content
    if source.startswith(("http://", "https://")):
        content = fetch_url(source)
        source_type = "URL"
    elif source.endswith(".pdf"):
        content = read_pdf(source)
        source_type = "PDF"
    else:
        content = read_text_file(source)
        source_type = "Text"

    # Check for errors
    if content.startswith("Error:"):
        raise ValueError(content)

    # Run the agent
    response = summarizer_agent.run(
        f"Please summarize the following {source_type} document:\n\n{content}"
    )

    if response.content and isinstance(response.content, DocumentSummary):
        return response.content
    else:
        raise ValueError("Failed to generate summary")


# ============================================================================
# Exports
# ============================================================================
__all__ = [
    "summarizer_agent",
    "summarize_document",
    "DocumentSummary",
]
