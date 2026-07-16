"""RecursiveChunking with overlap must not re-emit the tail as duplicate chunks."""

from agno.knowledge.chunking.recursive import RecursiveChunking
from agno.knowledge.document.base import Document


def _chunk(content, chunk_size=200, overlap=20):
    document = Document(content=content, name="x", meta_data={})
    return RecursiveChunking(chunk_size=chunk_size, overlap=overlap).chunk(document)


def test_overlap_does_not_emit_duplicate_tail_chunks():
    content = "This is a sentence about vectors. It has some words here. Another clause follows now. " * 6
    chunks = _chunk(content)

    # No chunk's content may be fully contained in an earlier chunk.
    for i in range(1, len(chunks)):
        for j in range(i):
            assert not (chunks[i].content and chunks[i].content in chunks[j].content), (
                f"chunk {i} duplicates content already in chunk {j}"
            )

    # The end of the content is still covered.
    assert content.rstrip()[-10:] in "".join(c.content for c in chunks)


def test_short_document_is_a_single_chunk():
    assert len(_chunk("short text")) == 1
