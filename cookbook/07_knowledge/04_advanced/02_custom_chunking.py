"""
Custom Chunking: Implementing Your Own Strategy
=================================================
When built-in strategies don't fit your content, implement a custom one.

A chunking strategy is a class that takes a Document and returns a list
of Document chunks. You control how content is split.

Use cases:
- Domain-specific splitting (legal clauses, medical records)
- Structured data (tables, forms)
- Content with custom delimiters

See also: ../02_building_blocks/01_chunking_strategies.py for built-in strategies.
"""

import asyncio

from agno.agent import Agent
from agno.knowledge.chunking.strategy import ChunkingStrategy
from agno.knowledge.document import Document
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.pdf_reader import PDFReader
from agno.models.openai import OpenAIResponses
from agno.vectordb.qdrant import Qdrant
from agno.vectordb.search import SearchType

# ---------------------------------------------------------------------------
# Custom Chunking Strategy
# ---------------------------------------------------------------------------


class ParagraphChunking(ChunkingStrategy):
    """Splits documents on double newlines (paragraphs).

    Each paragraph becomes its own chunk. Simple but effective
    for well-structured prose content.
    """

    def chunk(self, document: Document) -> list[Document]:
        chunks = []
        if not document.content:
            return chunks

        paragraphs = document.content.split("\n\n")
        for i, paragraph in enumerate(paragraphs):
            paragraph = paragraph.strip()
            if paragraph:
                chunks.append(
                    Document(
                        name="%s_chunk_%d" % (document.name, i),
                        content=paragraph,
                        meta_data={
                            **(document.meta_data or {}),
                            "chunk_index": i,
                            "chunking_strategy": "paragraph",
                        },
                    )
                )
        return chunks


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

qdrant_url = "http://localhost:6333"

knowledge = Knowledge(
    vector_db=Qdrant(
        collection="custom_chunking",
        url=qdrant_url,
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

# Use the custom chunking strategy with a PDF reader
reader = PDFReader(chunking_strategy=ParagraphChunking())

agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    knowledge=knowledge,
    search_knowledge=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":

    async def main():
        await knowledge.ainsert(
            url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
            reader=reader,
        )

        print("\n" + "=" * 60)
        print("Custom paragraph-based chunking")
        print("=" * 60 + "\n")

        agent.print_response("What Thai recipes do you know about?", stream=True)

    asyncio.run(main())
