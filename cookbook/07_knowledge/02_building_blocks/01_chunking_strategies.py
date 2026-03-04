"""
Chunking Strategies: Side-by-Side Comparison
==============================================
Chunking determines how documents are split into pieces for embedding and search.
The right strategy depends on your content type.

Strategies compared:
- Fixed size: Simple, predictable chunk sizes. Good default.
- Recursive: Splits on natural boundaries (paragraphs, sentences). Better quality.
- Semantic: Groups related sentences by meaning. Best for mixed-topic docs.
- Document: Splits on document structure (pages, sections).
- Markdown: Splits on headers. Ideal for structured documentation.
- Code: Respects function/class boundaries. Use for source code.
- Agentic: LLM determines optimal boundaries. Most accurate, slowest.

See also: ../reference/chunking_decision_guide.md
"""

import asyncio

from agno.agent import Agent
from agno.knowledge.chunking.agentic import AgenticChunking
from agno.knowledge.chunking.document import DocumentChunking
from agno.knowledge.chunking.fixed import FixedSizeChunking
from agno.knowledge.chunking.markdown import MarkdownChunking
from agno.knowledge.chunking.recursive import RecursiveChunking
from agno.knowledge.chunking.semantic import SemanticChunking
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.pdf_reader import PDFReader
from agno.models.openai import OpenAIResponses
from agno.vectordb.qdrant import Qdrant
from agno.vectordb.search import SearchType

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

qdrant_url = "http://localhost:6333"
pdf_url = "https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"


def create_knowledge(table_name: str) -> Knowledge:
    return Knowledge(
        vector_db=Qdrant(
            collection=table_name,
            url=qdrant_url,
            search_type=SearchType.hybrid,
            embedder=OpenAIEmbedder(id="text-embedding-3-small"),
        ),
    )


# ---------------------------------------------------------------------------
# Chunking Strategies
# ---------------------------------------------------------------------------

# 1. Fixed size: chunks of a set number of characters
fixed_reader = PDFReader(chunking_strategy=FixedSizeChunking(chunk_size=500))

# 2. Recursive: splits on paragraphs, then sentences, then characters
recursive_reader = PDFReader(chunking_strategy=RecursiveChunking(chunk_size=500))

# 3. Semantic: groups sentences by semantic similarity
semantic_reader = PDFReader(
    chunking_strategy=SemanticChunking(
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    )
)

# 4. Document: splits on document structure (pages)
document_reader = PDFReader(chunking_strategy=DocumentChunking())

# 5. Markdown: splits on headers (for markdown/docs content)
markdown_reader = PDFReader(chunking_strategy=MarkdownChunking())

# 6. Agentic: LLM decides where to split (slowest, most accurate)
agentic_reader = PDFReader(
    chunking_strategy=AgenticChunking(
        model=OpenAIResponses(id="gpt-5.2"),
    )
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":

    async def main():
        strategies = [
            ("fixed_chunking", "Fixed Size", fixed_reader),
            ("recursive_chunking", "Recursive", recursive_reader),
            ("semantic_chunking", "Semantic", semantic_reader),
            ("document_chunking", "Document", document_reader),
        ]

        for table_name, name, reader in strategies:
            print("\n" + "=" * 60)
            print("STRATEGY: %s" % name)
            print("=" * 60 + "\n")

            knowledge = create_knowledge(table_name)
            await knowledge.ainsert(url=pdf_url, reader=reader)

            agent = Agent(
                model=OpenAIResponses(id="gpt-5.2"),
                knowledge=knowledge,
                search_knowledge=True,
                markdown=True,
            )
            agent.print_response(
                "How do I make pad thai?",
                stream=True,
            )

    asyncio.run(main())
