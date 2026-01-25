"""
Document Summarizer
===================

An intelligent document summarization agent that processes various document
types and produces structured summaries.

Quick Start:
    from document_summarizer import summarizer_agent, summarize_document

    # Summarize a document
    summary = summarize_document("path/to/document.pdf")
    print(summary.summary)
    print(summary.key_points)
"""

from .agent import DocumentSummary, summarize_document, summarizer_agent
from .schemas import ActionItem, Entity

__all__ = [
    "summarizer_agent",
    "summarize_document",
    "DocumentSummary",
    "Entity",
    "ActionItem",
]
