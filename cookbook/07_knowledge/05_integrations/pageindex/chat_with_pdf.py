"""
PageIndex: Chat with a PDF Document
=====================================
Index a PDF into a hierarchical structure using LLM-powered extraction,
then chat with it using an agno Agent with session persistence.

Prerequisites:
    pip install agno[pageindex]
    export OPENAI_API_KEY=***

Usage:
    python chat_with_pdf.py /path/to/your/document.pdf

This example:
1. Indexes a PDF (one-time, skips if already indexed by content hash)
2. Creates an Agent with PageIndex knowledge + chat history
3. Asks questions and demonstrates multi-turn context awareness
"""

import sys

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.knowledge.pageindex import PageIndexKnowledge
from agno.models.openai import OpenAIChat

# ---------------------------------------------------------------------------
# 1. Setup PageIndex knowledge
# ---------------------------------------------------------------------------

knowledge = PageIndexKnowledge(
    results_dir="tmp/pageindex",
    tenant_id="demo",
)

# Index a PDF passed as argument (one-time -- skips if already indexed)
if len(sys.argv) > 1:
    pdf_path = sys.argv[1]
    print(f"Indexing: {pdf_path}")
    doc = knowledge.index_file(pdf_path)
    print(f"Indexed: {doc.doc_name} (id={doc.doc_id}, type={doc.doc_type})")

# ---------------------------------------------------------------------------
# 2. Create Agent with knowledge + chat history
# ---------------------------------------------------------------------------

agent = Agent(
    name="Document Assistant",
    model=OpenAIChat(id="gpt-4o"),
    knowledge=knowledge,
    search_knowledge=True,
    db=SqliteDb(db_file="tmp/pageindex/chat.db"),
    add_history_to_context=True,
    num_history_runs=4,
    instructions=[
        "You are a helpful assistant that answers questions about indexed documents.",
        "Always search the documents before answering.",
        "Cite specific sections when possible.",
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# 3. Chat
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    docs = knowledge.list_indexed_documents()
    if not docs:
        print("No documents indexed. Pass a PDF path as argument:")
        print("  python chat_with_pdf.py /path/to/document.pdf")
        sys.exit(1)

    print(f"\nIndexed documents: {len(docs)}")
    for d in docs:
        print(f"  - {d.doc_name} (id={d.doc_id})")

    # First question
    print("\n--- Question 1 ---")
    agent.print_response(
        "What is this document about? Give me a brief summary.", stream=True
    )

    # Follow-up (context-aware via history)
    print("\n--- Question 2 ---")
    agent.print_response("What are the main topics or sections covered?", stream=True)
