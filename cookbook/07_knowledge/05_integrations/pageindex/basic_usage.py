"""
PageIndex Knowledge: Hierarchical Document Indexing
=====================================================
Index PDF and Markdown documents into searchable hierarchical structures
using LLM-powered extraction, then search them with keyword retrieval.

No vector database or embeddings required.

Prerequisites:
    pip install agno[pageindex]
    export OPENAI_API_KEY=***

Steps:
1. Create a PageIndexKnowledge instance
2. Index one or more documents (one-time LLM-powered extraction)
3. Create an Agent with the knowledge attached
4. Ask questions -- the agent searches the indexed document structure
"""

from agno.agent import Agent
from agno.knowledge.pageindex import PageIndexKnowledge
from agno.models.openai import OpenAIChat

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

# Create a PageIndex knowledge base.
# Documents are indexed into hierarchical structures stored at results_dir.
knowledge = PageIndexKnowledge(
    results_dir="tmp/pageindex",
    tenant_id="demo",
)

# Index a PDF (one-time operation -- skips if already indexed by content hash).
# knowledge.index_file("path/to/report.pdf")

# Or index a Markdown file:
# knowledge.index_file("path/to/document.md")

# Or batch-index a directory of PDFs:
# knowledge.index_directory("path/to/docs/", glob_pattern="*.pdf")

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

# The agent gets search_documents, list_documents, and
# get_document_structure tools automatically via the knowledge protocol.
agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    knowledge=knowledge,
    search_knowledge=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # List what's indexed
    docs = knowledge.list_indexed_documents()
    if not docs:
        print("No documents indexed yet. Uncomment an index_file() call above.")
    else:
        for doc in docs:
            print(f"  {doc.doc_name} (id={doc.doc_id}, type={doc.doc_type})")

        # Ask the agent a question over the indexed documents
        agent.print_response(
            "Summarize the key topics covered in the documents", stream=True
        )
