"""Tests for MarkdownChunking with split_on_headings parameter."""

import pytest

pytest.importorskip("unstructured")

from agno.knowledge.chunking.markdown import MarkdownChunking
from agno.knowledge.document.base import Document

# Sample markdown content with multiple heading levels
MARKDOWN_CONTENT = """# Main Title (H1)

This is content under the main title.

## Section 1 (H2)

Content for section 1.

### Subsection 1.1 (H3)

Content for subsection 1.1.

### Subsection 1.2 (H3)

Content for subsection 1.2.

## Section 2 (H2)

Content for section 2.

### Subsection 2.1 (H3)

Content for subsection 2.1.

#### Details 2.1.1 (H4)

Detailed content.

## Section 3 (H2)

Final section content.
"""


# --- Tests for split_on_headings parameter ---


def test_split_on_headings_false_uses_size_based_chunking():
    """With split_on_headings=False, should use default size-based chunking."""
    chunker = MarkdownChunking(chunk_size=5000, split_on_headings=False)
    doc = Document(name="test.md", content=MARKDOWN_CONTENT)
    chunks = chunker.chunk(doc)

    # With large chunk_size and split_on_headings=False, should produce single chunk
    assert len(chunks) >= 1
    assert all(chunk.content for chunk in chunks)


def test_split_on_headings_true_splits_on_all_headings():
    """With split_on_headings=True, should split on all heading levels (H1-H6)."""
    chunker = MarkdownChunking(split_on_headings=True)
    doc = Document(name="test.md", content=MARKDOWN_CONTENT)
    chunks = chunker.chunk(doc)

    # Should create separate chunks for each heading
    # H1 (1) + H2 (3) + H3 (3) + H4 (1) = 8 total headings
    assert len(chunks) == 8

    # First chunk should start with H1
    assert chunks[0].content.startswith("# Main Title (H1)")

    # Check that each chunk has a heading
    for chunk in chunks:
        assert chunk.content.strip().startswith("#")


def test_split_on_headings_level_2_splits_on_h1_and_h2():
    """With split_on_headings=2, should split only on H1 and H2."""
    chunker = MarkdownChunking(split_on_headings=2)
    doc = Document(name="test.md", content=MARKDOWN_CONTENT)
    chunks = chunker.chunk(doc)

    # Should split on H1 and H2 only: 1 H1 + 3 H2 = 4 chunks
    assert len(chunks) == 4

    # First chunk should contain H1 and its content
    assert chunks[0].content.startswith("# Main Title (H1)")

    # Second chunk should start with H2 and contain H3 subsections
    assert chunks[1].content.startswith("## Section 1 (H2)")
    assert "### Subsection 1.1 (H3)" in chunks[1].content
    assert "### Subsection 1.2 (H3)" in chunks[1].content


def test_split_on_headings_level_1_splits_on_h1_only():
    """With split_on_headings=1, should split only on H1."""
    chunker = MarkdownChunking(split_on_headings=1)
    doc = Document(name="test.md", content=MARKDOWN_CONTENT)
    chunks = chunker.chunk(doc)

    # Should split on H1 only: 1 H1 = 1 chunk (all content under it)
    assert len(chunks) == 1

    # The chunk should contain all content including H2, H3, H4
    assert "# Main Title (H1)" in chunks[0].content
    assert "## Section 1 (H2)" in chunks[0].content
    assert "### Subsection 1.1 (H3)" in chunks[0].content
    assert "#### Details 2.1.1 (H4)" in chunks[0].content


def test_split_on_headings_level_3_splits_on_h1_h2_h3():
    """With split_on_headings=3, should split on H1, H2, and H3."""
    chunker = MarkdownChunking(split_on_headings=3)
    doc = Document(name="test.md", content=MARKDOWN_CONTENT)
    chunks = chunker.chunk(doc)

    # Should split on H1, H2, H3: 1 H1 + 3 H2 + 3 H3 = 7 chunks
    assert len(chunks) == 7

    # Find chunk with H4 - it should be within an H3 chunk
    h4_chunks = [c for c in chunks if "#### Details 2.1.1 (H4)" in c.content]
    assert len(h4_chunks) == 1
    # That chunk should start with H3
    assert h4_chunks[0].content.strip().startswith("### Subsection 2.1 (H3)")


def test_chunk_metadata_includes_chunk_number():
    """Chunks should include metadata with chunk number."""
    chunker = MarkdownChunking(split_on_headings=2)
    doc = Document(name="test.md", content=MARKDOWN_CONTENT, meta_data={"source": "test"})
    chunks = chunker.chunk(doc)

    for i, chunk in enumerate(chunks, 1):
        assert chunk.meta_data["chunk"] == i
        assert chunk.meta_data["source"] == "test"  # Original metadata preserved
        assert "chunk_size" in chunk.meta_data


def test_chunk_ids_include_chunk_number():
    """Chunk IDs should include chunk number when document has ID."""
    chunker = MarkdownChunking(split_on_headings=True)
    doc = Document(id="doc123", name="test.md", content=MARKDOWN_CONTENT)
    chunks = chunker.chunk(doc)

    for i, chunk in enumerate(chunks, 1):
        assert chunk.id == f"doc123_{i}"


def test_chunk_ids_use_name_when_no_id():
    """Chunk IDs should use document name when no ID provided."""
    chunker = MarkdownChunking(split_on_headings=True)
    doc = Document(name="test.md", content=MARKDOWN_CONTENT)
    chunks = chunker.chunk(doc)

    for i, chunk in enumerate(chunks, 1):
        assert chunk.id == f"test.md_{i}"


# --- Tests for parameter validation ---


def test_invalid_heading_level_above_6_raises_error():
    """split_on_headings must be between 1 and 6."""
    with pytest.raises(ValueError, match="split_on_headings must be between 1 and 6"):
        MarkdownChunking(split_on_headings=7)


def test_invalid_heading_level_below_1_raises_error():
    """split_on_headings must be between 1 and 6."""
    with pytest.raises(ValueError, match="split_on_headings must be between 1 and 6"):
        MarkdownChunking(split_on_headings=0)


def test_negative_heading_level_raises_error():
    """Negative heading levels should raise ValueError."""
    with pytest.raises(ValueError, match="split_on_headings must be between 1 and 6"):
        MarkdownChunking(split_on_headings=-1)


def test_valid_heading_levels_1_to_6_accepted():
    """All valid heading levels from 1 to 6 should be accepted."""
    for level in range(1, 7):
        chunker = MarkdownChunking(split_on_headings=level)
        assert chunker.split_on_headings == level


# --- Tests for edge cases ---


def test_empty_content_returns_single_chunk():
    """Empty content should return single chunk."""
    chunker = MarkdownChunking(split_on_headings=True)
    doc = Document(name="test.md", content="")
    chunks = chunker.chunk(doc)

    assert len(chunks) == 1
    assert chunks[0].content == ""


def test_content_smaller_than_chunk_size_returns_single_chunk():
    """Content smaller than chunk_size should return single chunk."""
    small_content = "# Small Heading\n\nSmall content."
    chunker = MarkdownChunking(chunk_size=5000, split_on_headings=False)
    doc = Document(name="test.md", content=small_content)
    chunks = chunker.chunk(doc)

    assert len(chunks) == 1
    assert chunks[0].content == small_content


def test_no_headings_with_split_on_headings_true():
    """Content without headings should return single chunk even with split_on_headings=True."""
    no_heading_content = "Just some plain text without any headings.\n\nAnother paragraph."
    chunker = MarkdownChunking(split_on_headings=True)
    doc = Document(name="test.md", content=no_heading_content)
    chunks = chunker.chunk(doc)

    assert len(chunks) == 1
    assert no_heading_content in chunks[0].content


def test_only_lower_level_headings_with_high_split_level():
    """Content with only H3-H6 when split_on_headings=2 should return single chunk."""
    low_level_content = """### Heading 3

Content under H3.

#### Heading 4

Content under H4.
"""
    chunker = MarkdownChunking(split_on_headings=2)  # Only splits on H1 and H2
    doc = Document(name="test.md", content=low_level_content)
    chunks = chunker.chunk(doc)

    # Should not split since no H1 or H2 present
    assert len(chunks) == 1
    assert "### Heading 3" in chunks[0].content
    assert "#### Heading 4" in chunks[0].content


def test_mixed_heading_levels_with_level_4_split():
    """Test splitting on H1-H4 with mixed heading levels."""
    mixed_content = """# H1

## H2

### H3

#### H4

##### H5

###### H6
"""
    chunker = MarkdownChunking(split_on_headings=4)
    doc = Document(name="test.md", content=mixed_content)
    chunks = chunker.chunk(doc)

    # Should split on H1, H2, H3, H4 = 4 chunks
    # H5 and H6 should be part of H4 chunk
    assert len(chunks) == 4
    assert "##### H5" in chunks[3].content
    assert "###### H6" in chunks[3].content


# --- Tests for fallback behavior ---


def test_fallback_splits_at_paragraphs():
    """When markdown parsing fails, should fall back to paragraph splitting."""
    from unittest.mock import patch

    text = """First paragraph.

Second paragraph.

Third paragraph."""

    doc = Document(id="test", name="test", content=text)
    chunker = MarkdownChunking(chunk_size=30, overlap=0)

    with patch("agno.knowledge.chunking.markdown.partition_md", side_effect=Exception("test")):
        chunks = chunker.chunk(doc)

    assert len(chunks) > 1


# --- Tests for overlap functionality ---


def test_overlap_prepends_content_from_previous_chunk():
    """Overlap should prepend content from previous chunk."""
    content = """# Section 1

First section content here.

## Section 2

Second section content here.

## Section 3

Third section content here.
"""
    chunker = MarkdownChunking(split_on_headings=True, overlap=10)
    doc = Document(name="test.md", content=content)
    chunks = chunker.chunk(doc)

    # Second chunk onwards should have overlap from previous chunk
    assert len(chunks) == 3
    # Check that chunks after first have content prepended
    for i in range(1, len(chunks)):
        prev_ending = chunks[i - 1].content[-10:]
        assert chunks[i].content.startswith(prev_ending)


def test_overlap_with_size_based_chunking():
    """Overlap should work with size-based chunking."""
    from unittest.mock import patch

    long_content = "Paragraph one. " * 20 + "\n\n" + "Paragraph two. " * 20 + "\n\n" + "Paragraph three. " * 20
    chunker = MarkdownChunking(chunk_size=200, overlap=30, split_on_headings=False)
    doc = Document(name="test.md", content=long_content)

    with patch("agno.knowledge.chunking.markdown.partition_md", side_effect=Exception("force fallback")):
        chunks = chunker.chunk(doc)

    assert len(chunks) > 1
    # Verify overlap exists in subsequent chunks
    for i in range(1, len(chunks)):
        prev_ending = chunks[i - 1].content[-30:]
        assert prev_ending in chunks[i].content


# --- Tests for unicode and international content ---


def test_unicode_headings_and_content():
    """Headings and content with unicode characters should be handled correctly."""
    content = """# Documentation en Francais

Contenu avec des accents: cafe, facade, resume.

## Abschnitt auf Deutsch

Umlaute: Muller, Geschaft, Ubung.

## Sekcja po Polsku

Polskie znaki: zolty, zrodlo, swieto.
"""
    chunker = MarkdownChunking(split_on_headings=True)
    doc = Document(name="test.md", content=content)
    chunks = chunker.chunk(doc)

    assert len(chunks) == 3
    assert "Francais" in chunks[0].content
    assert "Deutsch" in chunks[1].content
    assert "Polsku" in chunks[2].content


def test_cjk_characters_in_markdown():
    """Chinese, Japanese, Korean characters should be handled correctly."""
    content = """# Chinese Section

This section has content.

## Japanese Section

More content here.

## Korean Section

Final content.
"""
    chunker = MarkdownChunking(split_on_headings=True)
    doc = Document(name="test.md", content=content)
    chunks = chunker.chunk(doc)

    assert len(chunks) == 3
    assert "Chinese" in chunks[0].content
    assert "Japanese" in chunks[1].content
    assert "Korean" in chunks[2].content


# --- Tests for size-based chunking creating multiple chunks ---


def test_size_based_chunking_creates_multiple_chunks_when_content_exceeds_limit():
    """When split_on_headings=False and content exceeds chunk_size, should create multiple chunks."""
    from unittest.mock import patch

    # Create content that definitely exceeds chunk_size
    long_content = ("This is paragraph one with some content. " * 10 + "\n\n") * 10
    chunker = MarkdownChunking(chunk_size=200, split_on_headings=False)
    doc = Document(name="test.md", content=long_content)

    # Force fallback to ensure size-based chunking behavior
    with patch("agno.knowledge.chunking.markdown.partition_md", side_effect=Exception("force fallback")):
        chunks = chunker.chunk(doc)

    assert len(chunks) > 1
    # Verify chunk numbers are sequential
    for i, chunk in enumerate(chunks, 1):
        assert chunk.meta_data["chunk"] == i


# --- Tests for split_on_headings respecting chunk_size ---


def test_split_on_headings_respects_chunk_size():
    """Large sections should be split to respect chunk_size even with split_on_headings enabled."""
    # Create content with a very large section under one heading
    large_section = "This is a long paragraph with lots of content. " * 50  # ~2400 chars
    content = f"""# Section 1

{large_section}

## Section 2

Short content here.
"""
    chunker = MarkdownChunking(chunk_size=500, split_on_headings=True)
    doc = Document(name="test.md", content=content)
    chunks = chunker.chunk(doc)

    # Should create multiple chunks for the large section
    assert len(chunks) > 2  # More than just 2 sections

    # All chunks should respect chunk_size
    for chunk in chunks:
        assert len(chunk.content) <= 500, f"Chunk exceeds chunk_size: {len(chunk.content)} > 500"


def test_split_on_headings_preserves_heading_in_sub_chunks():
    """When splitting large sections, the heading should be preserved in each sub-chunk."""
    # Create content with a large section
    large_section = "Word " * 200  # ~1000 chars of content
    content = f"""# My Important Heading

{large_section}
"""
    chunker = MarkdownChunking(chunk_size=300, split_on_headings=True)
    doc = Document(name="test.md", content=content)
    chunks = chunker.chunk(doc)

    # Should have multiple chunks
    assert len(chunks) > 1

    # Each chunk should start with the heading
    for chunk in chunks:
        assert chunk.content.startswith("# My Important Heading"), (
            f"Chunk should start with heading, got: {chunk.content[:50]}..."
        )


def test_split_on_headings_level_2_respects_chunk_size():
    """Large H2 sections should be split to respect chunk_size with split_on_headings=2."""
    large_content = "Content here. " * 100  # ~1400 chars
    content = f"""# Main Title

Intro text.

## Large Section

{large_content}

## Small Section

Just a little text.
"""
    chunker = MarkdownChunking(chunk_size=400, split_on_headings=2)
    doc = Document(name="test.md", content=content)
    chunks = chunker.chunk(doc)

    # Should split the large section
    assert len(chunks) > 3  # More than just H1, H2 large, H2 small

    # All chunks should respect chunk_size
    for chunk in chunks:
        assert len(chunk.content) <= 400, f"Chunk exceeds chunk_size: {len(chunk.content)} > 400"


def test_split_on_headings_small_sections_not_affected():
    """Small sections should remain as single chunks when split_on_headings is enabled."""
    content = """# Section 1

Short content.

## Section 2

Also short.

### Section 3

Brief text.
"""
    chunker = MarkdownChunking(chunk_size=500, split_on_headings=True)
    doc = Document(name="test.md", content=content)
    chunks = chunker.chunk(doc)

    # Should have exactly 3 chunks (one per heading)
    assert len(chunks) == 3

    # Verify content matches expected sections
    assert "# Section 1" in chunks[0].content
    assert "## Section 2" in chunks[1].content
    assert "### Section 3" in chunks[2].content


def test_split_on_headings_very_long_paragraph_split_by_words():
    """A single very long paragraph should be split by words to respect chunk_size."""
    # Create a paragraph that is much larger than chunk_size
    long_paragraph = "word " * 500  # ~2500 chars
    content = f"""# Heading

{long_paragraph}
"""
    chunker = MarkdownChunking(chunk_size=200, split_on_headings=True)
    doc = Document(name="test.md", content=content)
    chunks = chunker.chunk(doc)

    # Should create multiple chunks
    assert len(chunks) > 5

    # All chunks should respect chunk_size
    for chunk in chunks:
        assert len(chunk.content) <= 200, f"Chunk exceeds chunk_size: {len(chunk.content)} > 200"


def test_split_on_headings_chunk_metadata_correct_with_splitting():
    """Chunk metadata should be correct when large sections are split."""
    large_content = "Some text here. " * 50  # ~800 chars
    content = f"""# Section

{large_content}
"""
    chunker = MarkdownChunking(chunk_size=200, split_on_headings=True)
    doc = Document(id="doc1", name="test.md", content=content, meta_data={"source": "test"})
    chunks = chunker.chunk(doc)

    # Verify sequential chunk numbers and correct IDs
    for i, chunk in enumerate(chunks, 1):
        assert chunk.meta_data["chunk"] == i
        assert chunk.meta_data["source"] == "test"
        assert chunk.id == f"doc1_{i}"
        assert chunk.meta_data["chunk_size"] == len(chunk.content)


def test_split_on_headings_overlap_between_sub_chunks():
    """Overlap should be applied between sub-chunks from split large sections."""
    # Create a large section that will be split into multiple sub-chunks
    large_content = "Word1 Word2 Word3. " * 30  # ~570 chars
    content = f"""# Big Section

{large_content}
"""
    chunker = MarkdownChunking(chunk_size=200, split_on_headings=True, overlap=20)
    doc = Document(name="test.md", content=content)
    chunks = chunker.chunk(doc)

    # Should have multiple chunks
    assert len(chunks) > 1

    # Verify overlap exists between consecutive chunks
    for i in range(1, len(chunks)):
        # The end of previous chunk should appear at start of current chunk
        prev_ending = chunks[i - 1].content[-20:]
        assert chunks[i].content.startswith(prev_ending), f"Chunk {i + 1} should start with overlap from chunk {i}"
