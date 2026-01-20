"""
Internal Knowledge Agent
========================

A RAG-powered knowledge agent that provides intelligent access to internal company
documentation with source citations and conversation history.
"""

from agent import company_knowledge, knowledge_agent

__all__ = [
    "knowledge_agent",
    "company_knowledge",
]
