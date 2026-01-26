"""
Demonstrates chunk ID generation fallback chain.

When chunking Documents, IDs are generated using this priority:
1. document.id -> "{id}_{chunk_number}"
2. document.name -> "{name}_{chunk_number}"
3. content hash -> "chunk_{hash}_{chunk_number}"

This ensures chunks always have deterministic IDs, even when Documents
are created without explicit identifiers (e.g., from API responses,
user input, or web scraping).
"""

from agno.knowledge.chunking.fixed import FixedSizeChunking
from agno.knowledge.chunking.document import DocumentChunking
from agno.knowledge.chunking.row import RowChunking
from agno.knowledge.document.base import Document

# Sample content (simulating text from an API or user input)
content = """
Machine learning is a subset of artificial intelligence that enables
systems to learn and improve from experience without being explicitly
programmed. It focuses on developing algorithms that can access data
and use it to learn for themselves.

Deep learning is a subset of machine learning that uses neural networks
with many layers. These deep neural networks attempt to simulate the
behavior of the human brain in processing data and creating patterns.
"""


def main():
    print("=" * 70)
    print("Chunk ID Fallback Chain Demo")
    print("=" * 70)

    # Case 1: Document with explicit id (highest priority)
    print("\n1. Document with id='ml-guide':")
    print("-" * 40)
    doc = Document(id="ml-guide", content=content)
    chunks = FixedSizeChunking(chunk_size=200).chunk(doc)
    for i, chunk in enumerate(chunks[:3]):
        print(f"   Chunk {i+1}: id={chunk.id}")

    # Case 2: Document with name only (second priority)
    print("\n2. Document with name='article.txt':")
    print("-" * 40)
    doc = Document(name="article.txt", content=content)
    chunks = FixedSizeChunking(chunk_size=200).chunk(doc)
    for i, chunk in enumerate(chunks[:3]):
        print(f"   Chunk {i+1}: id={chunk.id}")

    # Case 3: Document with only content (uses hash fallback)
    print("\n3. Document with content only (no id/name):")
    print("-" * 40)
    doc = Document(content=content)
    chunks = FixedSizeChunking(chunk_size=200).chunk(doc)
    for i, chunk in enumerate(chunks[:3]):
        print(f"   Chunk {i+1}: id={chunk.id}")

    # Case 4: Verify determinism - same content produces same IDs
    print("\n4. Determinism check (same content = same IDs):")
    print("-" * 40)
    doc1 = Document(content=content)
    doc2 = Document(content=content)
    chunks1 = FixedSizeChunking(chunk_size=200).chunk(doc1)
    chunks2 = FixedSizeChunking(chunk_size=200).chunk(doc2)
    ids_match = all(c1.id == c2.id for c1, c2 in zip(chunks1, chunks2))
    print(f"   First run:  {chunks1[0].id}")
    print(f"   Second run: {chunks2[0].id}")
    print(f"   IDs match: {ids_match}")

    # Case 5: Different content produces different IDs
    print("\n5. Uniqueness check (different content = different IDs):")
    print("-" * 40)
    doc_a = Document(content="Content A - about machine learning")
    doc_b = Document(content="Content B - about deep learning")
    chunks_a = FixedSizeChunking(chunk_size=100).chunk(doc_a)
    chunks_b = FixedSizeChunking(chunk_size=100).chunk(doc_b)
    print(f"   Content A: {chunks_a[0].id}")
    print(f"   Content B: {chunks_b[0].id}")
    print(f"   IDs different: {chunks_a[0].id != chunks_b[0].id}")

    # Case 6: RowChunking uses "_row_" prefix
    print("\n6. RowChunking with content only:")
    print("-" * 40)
    csv_content = "row1,data1\nrow2,data2\nrow3,data3"
    doc = Document(content=csv_content)
    chunks = RowChunking().chunk(doc)
    for i, chunk in enumerate(chunks[:3]):
        print(f"   Chunk {i+1}: id={chunk.id}")

    # Case 7: DocumentChunking also uses fallback
    print("\n7. DocumentChunking with content only:")
    print("-" * 40)
    doc = Document(content=content)
    chunks = DocumentChunking(chunk_size=200).chunk(doc)
    for i, chunk in enumerate(chunks[:3]):
        print(f"   Chunk {i+1}: id={chunk.id}")

    print("\n" + "=" * 70)
    print("All chunks have valid, deterministic IDs!")
    print("=" * 70)


if __name__ == "__main__":
    main()
