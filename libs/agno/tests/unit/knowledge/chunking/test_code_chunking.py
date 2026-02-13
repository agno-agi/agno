"""Tests for CodeChunking wrapper around chonkie's CodeChunker."""

from typing import Sequence

import pytest

from agno.knowledge.chunking.code import CodeChunking
from agno.knowledge.document.base import Document


@pytest.fixture
def sample_python_code():
    """Sample Python code for testing."""
    return """def function1():
    x = 1
    return x

def function2():
    y = 2
    return y

def function3():
    z = 3
    return z"""


@pytest.fixture
def sample_javascript_code():
    """Sample JavaScript code for testing."""
    return """function hello() {
    return "world";
}

function goodbye() {
    return "moon";
}"""


def test_code_chunking_basic(sample_python_code):
    """Test basic code chunking with default parameters."""
    chunker = CodeChunking()
    doc = Document(content=sample_python_code, name="test.py")

    chunks = chunker.chunk(doc)

    assert len(chunks) > 0
    assert all(isinstance(chunk, Document) for chunk in chunks)
    assert all(chunk.content for chunk in chunks)


def test_code_chunking_character_tokenizer(sample_python_code):
    """Test with character tokenizer."""
    chunker = CodeChunking(tokenizer="character", chunk_size=50, language="python")
    doc = Document(content=sample_python_code, name="test.py")

    chunks = chunker.chunk(doc)

    assert len(chunks) > 0
    assert all(chunk.content for chunk in chunks)


def test_code_chunking_word_tokenizer(sample_python_code):
    """Test with word tokenizer."""
    chunker = CodeChunking(tokenizer="word", chunk_size=20, language="python")
    doc = Document(content=sample_python_code, name="test.py")

    chunks = chunker.chunk(doc)

    assert len(chunks) > 0
    assert all(chunk.content for chunk in chunks)


def test_code_chunking_gpt2_tokenizer(sample_python_code):
    """Test with gpt2 tokenizer."""
    chunker = CodeChunking(tokenizer="gpt2", chunk_size=30, language="python")
    doc = Document(content=sample_python_code, name="test.py")

    chunks = chunker.chunk(doc)

    assert len(chunks) > 0
    assert all(chunk.content for chunk in chunks)


def test_code_chunking_cl100k_tokenizer(sample_python_code):
    """Test with cl100k_base tokenizer."""
    chunker = CodeChunking(tokenizer="cl100k_base", chunk_size=30, language="python")
    doc = Document(content=sample_python_code, name="test.py")

    chunks = chunker.chunk(doc)

    assert len(chunks) > 0
    assert all(chunk.content for chunk in chunks)


def test_code_chunking_python_language(sample_python_code):
    """Test with explicit Python language."""
    chunker = CodeChunking(tokenizer="character", chunk_size=100, language="python")
    doc = Document(content=sample_python_code, name="test.py")

    chunks = chunker.chunk(doc)

    assert len(chunks) > 0
    # Content should be preserved exactly
    combined = "".join(chunk.content for chunk in chunks)
    assert combined == sample_python_code


def test_code_chunking_javascript_language(sample_javascript_code):
    """Test with JavaScript language."""
    chunker = CodeChunking(tokenizer="character", chunk_size=50, language="javascript")
    doc = Document(content=sample_javascript_code, name="test.js")

    chunks = chunker.chunk(doc)

    assert len(chunks) > 0
    combined = "".join(chunk.content for chunk in chunks)
    assert combined == sample_javascript_code


def test_code_chunking_auto_language(sample_python_code):
    """Test with auto language detection."""
    chunker = CodeChunking(tokenizer="character", chunk_size=100, language="auto")
    doc = Document(content=sample_python_code, name="test.py")

    chunks = chunker.chunk(doc)

    assert len(chunks) > 0


def test_code_chunking_include_nodes_false(sample_python_code):
    """Test with include_nodes=False (default)."""
    chunker = CodeChunking(include_nodes=False, language="python")
    doc = Document(content=sample_python_code, name="test.py")

    chunks = chunker.chunk(doc)

    assert len(chunks) > 0
    assert all(chunk.content for chunk in chunks)


def test_code_chunking_include_nodes_true(sample_python_code):
    """Test with include_nodes=True."""
    chunker = CodeChunking(include_nodes=True, language="python")
    doc = Document(content=sample_python_code, name="test.py")

    chunks = chunker.chunk(doc)

    assert len(chunks) > 0
    assert all(chunk.content for chunk in chunks)


def test_code_chunking_preserves_content(sample_python_code):
    """Test that all content is preserved after chunking."""
    chunker = CodeChunking(tokenizer="character", chunk_size=50, language="python")
    doc = Document(content=sample_python_code, name="test.py")

    chunks = chunker.chunk(doc)

    # Combine all chunks
    combined = "".join(chunk.content for chunk in chunks)

    # Should match original exactly
    assert combined == sample_python_code
    assert len(combined) == len(sample_python_code)


def test_code_chunking_metadata(sample_python_code):
    """Test that chunks have correct metadata."""
    chunker = CodeChunking(language="python")
    doc = Document(id="test-123", name="test.py", content=sample_python_code, meta_data={"author": "test"})

    chunks = chunker.chunk(doc)

    for i, chunk in enumerate(chunks, 1):
        assert chunk.id == f"test-123_{i}"
        assert chunk.name == "test.py"
        assert chunk.meta_data["chunk"] == i
        assert chunk.meta_data["author"] == "test"
        assert "chunk_size" in chunk.meta_data
        assert chunk.meta_data["chunk_size"] == len(chunk.content)


def test_code_chunking_empty_content():
    """Test handling of empty content."""
    chunker = CodeChunking()
    doc = Document(content="", name="empty.py")

    chunks = chunker.chunk(doc)

    # Should return original document
    assert len(chunks) == 1
    assert chunks[0] is doc


def test_code_chunking_whitespace_only():
    """Test handling of whitespace-only content."""
    chunker = CodeChunking(language="python")
    doc = Document(content="   \n\n   ", name="whitespace.py")

    chunks = chunker.chunk(doc)

    # chonkie returns empty list for whitespace-only
    assert len(chunks) == 0


def test_code_chunking_single_line():
    """Test chunking single line of code."""
    chunker = CodeChunking(tokenizer="character", chunk_size=100, language="python")
    doc = Document(content="x = 1", name="single.py")

    chunks = chunker.chunk(doc)

    assert len(chunks) == 1
    assert chunks[0].content == "x = 1"


def test_code_chunking_preserves_newlines():
    """Test that newlines are preserved in chunked content."""
    code = "def test():\n    pass\n\ndef other():\n    pass\n"
    chunker = CodeChunking(tokenizer="character", chunk_size=30, language="python")
    doc = Document(content=code, name="test.py")

    chunks = chunker.chunk(doc)

    combined = "".join(chunk.content for chunk in chunks)
    assert combined == code
    assert combined.count("\n") == code.count("\n")


def test_code_chunking_preserves_indentation():
    """Test that indentation is preserved."""
    code = """def hello():
    if True:
        print("nested")
    return True"""

    chunker = CodeChunking(tokenizer="character", chunk_size=50, language="python")
    doc = Document(content=code, name="test.py")

    chunks = chunker.chunk(doc)

    combined = "".join(chunk.content for chunk in chunks)
    assert combined == code
    # Check that indentation is preserved
    assert "    if True:" in combined
    assert "        print" in combined


def test_code_chunking_unicode_content():
    """Test handling of unicode characters in code."""
    code = 'def hello():\n    return "Hello 世界 🌍"'
    chunker = CodeChunking(tokenizer="character", chunk_size=50, language="python")
    doc = Document(content=code, name="unicode.py")

    chunks = chunker.chunk(doc)

    combined = "".join(chunk.content for chunk in chunks)
    assert combined == code
    assert "世界" in combined
    assert "🌍" in combined


def test_code_chunking_various_chunk_sizes(sample_python_code):
    """Test with various chunk sizes."""
    sizes = [10, 50, 100, 500, 2000]

    for size in sizes:
        chunker = CodeChunking(tokenizer="character", chunk_size=size, language="python")
        doc = Document(content=sample_python_code, name="test.py")

        chunks = chunker.chunk(doc)

        assert len(chunks) > 0
        combined = "".join(chunk.content for chunk in chunks)
        assert combined == sample_python_code


def test_code_chunking_custom_tokenizer_subclass(sample_python_code):
    """Test with custom Tokenizer subclass."""
    from chonkie.tokenizer import Tokenizer

    class LineTokenizer(Tokenizer):
        """Custom tokenizer that counts lines of code."""

        def __init__(self):
            self.vocab = []
            self.token2id = {}

        def __repr__(self) -> str:
            return "LineTokenizer()"

        def tokenize(self, text: str) -> Sequence[str]:
            if not text:
                return []
            return text.split("\n")

        def encode(self, text: str) -> Sequence[int]:
            encoded = []
            for token in self.tokenize(text):
                if token not in self.token2id:
                    self.token2id[token] = len(self.vocab)
                    self.vocab.append(token)
                encoded.append(self.token2id[token])
            return encoded

        def decode(self, tokens: Sequence[int]) -> str:
            try:
                return "\n".join([self.vocab[token] for token in tokens])
            except Exception as e:
                raise ValueError(f"Decoding failed. Tokens: {tokens} not found in vocab.") from e

        def count_tokens(self, text: str) -> int:
            if not text:
                return 0
            return len(text.split("\n"))

    chunker = CodeChunking(tokenizer=LineTokenizer(), chunk_size=10, language="python")
    doc = Document(content=sample_python_code, name="test.py")

    chunks = chunker.chunk(doc)

    assert len(chunks) > 0
    assert all(chunk.content for chunk in chunks)


def test_code_chunking_no_document_id(sample_python_code):
    """Test chunking document without id uses name as fallback."""
    chunker = CodeChunking(language="python")
    doc = Document(content=sample_python_code, name="test.py")  # No id, but has name

    chunks = chunker.chunk(doc)

    assert len(chunks) > 0
    # Chunks should have name-based IDs when document has name but no id
    assert all(chunk.id is not None and chunk.id.startswith("test.py_") for chunk in chunks)


def test_code_chunking_lazy_initialization(sample_python_code):
    """Test that chunker is initialized lazily."""
    chunker = CodeChunking(language="python")

    # Chunker should not be initialized yet
    assert chunker.chunker is None

    # After first chunk() call, it should be initialized
    doc = Document(content=sample_python_code, name="test.py")
    _ = chunker.chunk(doc)

    assert chunker.chunker is not None
