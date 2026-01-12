# Adding New Factory Readers

This guide explains how to add a new reader to the Agno knowledge system. Readers are responsible for extracting content from various sources (files, URLs, APIs) and converting them into `Document` objects for the knowledge base.

## Overview

A reader must:
1. Extend the `Reader` base class
2. Implement required methods for reading content
3. Declare supported chunking strategies and content types
4. Be registered in the `ReaderFactory`

## Step-by-Step Guide

### 1. Create the Reader File

Create a new file in `libs/agno/agno/knowledge/reader/` named `{name}_reader.py`:

```python
from typing import Any, List, Optional

from agno.knowledge.chunking.strategy import ChunkingStrategyType
from agno.knowledge.document.base import Document
from agno.knowledge.reader.base import Reader
from agno.knowledge.types import ContentType


class MyNewReader(Reader):
    """Reader for processing [describe your content type]."""

    def __init__(
        self,
        # Add any reader-specific parameters here
        custom_option: str = "default",
        # Always include base class parameters
        chunk: bool = True,
        chunk_size: int = 5000,
        name: Optional[str] = None,
        description: Optional[str] = None,
        **kwargs,
    ) -> None:
        super().__init__(
            chunk=chunk,
            chunk_size=chunk_size,
            name=name,
            description=description,
            **kwargs,
        )
        self.custom_option = custom_option

    @classmethod
    def get_supported_chunking_strategies(cls) -> List[ChunkingStrategyType]:
        """Return the list of chunking strategies this reader supports."""
        return [
            ChunkingStrategyType.FIXED_SIZE_CHUNKER,
            ChunkingStrategyType.DOCUMENT_CHUNKER,
            # Add other supported strategies
        ]

    @classmethod
    def get_supported_content_types(cls) -> List[ContentType]:
        """Return the list of content types this reader can process."""
        return [
            ContentType.FILE,  # or ContentType.URL, ContentType.PDF, etc.
        ]

    def read(
        self,
        source: Any,
        name: Optional[str] = None,
        **kwargs,
    ) -> List[Document]:
        """
        Synchronously read content from the source.

        Args:
            source: The source to read from (file path, URL, bytes, etc.)
            name: Optional name for the document

        Returns:
            List of Document objects
        """
        # Implement your reading logic here
        content = self._extract_content(source)

        documents = [
            Document(
                name=name or "document",
                content=content,
                meta_data={"source_type": "my_new_reader"},
            )
        ]

        # Handle chunking if enabled
        if self.chunk:
            chunked_docs = []
            for doc in documents:
                chunked_docs.extend(self.chunk_document(doc))
            return chunked_docs

        return documents

    async def async_read(
        self,
        source: Any,
        name: Optional[str] = None,
        **kwargs,
    ) -> List[Document]:
        """
        Asynchronously read content from the source.

        Args:
            source: The source to read from
            name: Optional name for the document

        Returns:
            List of Document objects
        """
        # For simple cases, you can call the sync version
        # For I/O-bound operations, implement true async logic
        import asyncio
        return await asyncio.to_thread(self.read, source, name, **kwargs)

    def _extract_content(self, source: Any) -> str:
        """Helper method to extract content from the source."""
        # Implement your content extraction logic
        pass
```

### 2. Register in ReaderFactory

Update `libs/agno/agno/knowledge/reader/reader_factory.py`:

#### a) Add metadata to `READER_METADATA`:

```python
READER_METADATA: Dict[str, Dict[str, str]] = {
    # ... existing readers ...
    "my_new": {
        "name": "MyNewReader",
        "description": "Processes [describe what it does]",
    },
}
```

#### b) Add class mapping in `get_reader_class()`:

```python
@classmethod
def get_reader_class(cls, reader_key: str) -> type:
    reader_class_map: Dict[str, tuple] = {
        # ... existing mappings ...
        "my_new": ("agno.knowledge.reader.my_new_reader", "MyNewReader"),
    }
```

#### c) Add factory method:

```python
@classmethod
def _get_my_new_reader(cls, **kwargs) -> Reader:
    """Get MyNew reader instance."""
    from agno.knowledge.reader.my_new_reader import MyNewReader

    config: Dict[str, Any] = {
        "name": "MyNew Reader",
        "description": "Processes [describe what it does]",
    }
    config.update(kwargs)
    return MyNewReader(**config)
```

#### d) (Optional) Add extension mapping:

If your reader handles specific file extensions, update `get_reader_for_extension()`:

```python
@classmethod
def get_reader_for_extension(cls, extension: str) -> Reader:
    extension = extension.lower()
    # ... existing mappings ...
    elif extension == ".mynew":
        return cls.create_reader("my_new")
```

### 3. Available Chunking Strategies

Choose from these chunking strategies based on your content type:

| Strategy | Best For | Description |
|----------|----------|-------------|
| `FIXED_SIZE_CHUNKER` | Generic text | Splits into fixed-size chunks |
| `DOCUMENT_CHUNKER` | Structured docs | Preserves document structure |
| `AGENTIC_CHUNKER` | Complex content | AI-assisted chunking |
| `SEMANTIC_CHUNKER` | Semantic boundaries | Groups semantically related content |
| `RECURSIVE_CHUNKER` | Hierarchical content | Recursively splits on separators |
| `ROW_CHUNKER` | Tabular data | Each row becomes a document |
| `MARKDOWN_CHUNKER` | Markdown files | Respects markdown structure |

### 4. Available Content Types

Declare which content types your reader supports:

```python
class ContentType(str, Enum):
    FILE = "file"       # Generic file
    URL = "url"         # Web URLs
    TEXT = "text"       # Plain text
    TOPIC = "topic"     # Topic-based content
    YOUTUBE = "youtube" # YouTube videos
    PDF = ".pdf"
    TXT = ".txt"
    MARKDOWN = ".md"
    DOCX = ".docx"
    DOC = ".doc"
    PPTX = ".pptx"
    JSON = ".json"
    CSV = ".csv"
    XLSX = ".xlsx"
    XLS = ".xls"
```

## Testing Your Reader

### 1. Unit Test

Create a test file `tests/knowledge/reader/test_my_new_reader.py`:

```python
import pytest
from agno.knowledge.reader.my_new_reader import MyNewReader


def test_read_basic():
    reader = MyNewReader()
    docs = reader.read("sample content")
    assert len(docs) > 0
    assert docs[0].content is not None


def test_supported_strategies():
    strategies = MyNewReader.get_supported_chunking_strategies()
    assert len(strategies) > 0


def test_supported_content_types():
    content_types = MyNewReader.get_supported_content_types()
    assert len(content_types) > 0
```

### 2. Integration Test

Verify your reader appears in the config endpoint:

```python
# Start your AgentOS app and call /knowledge/config
# Your reader should appear in the "readers" response
```

### 3. Manual Testing

```python
from agno.knowledge.reader.my_new_reader import MyNewReader

reader = MyNewReader()
docs = reader.read("/path/to/sample/file")
for doc in docs:
    print(f"Name: {doc.name}")
    print(f"Content: {doc.content[:100]}...")
```

## Best Practices

1. **Handle errors gracefully**: Wrap I/O operations in try-except blocks
2. **Support both sync and async**: Implement both `read()` and `async_read()`
3. **Respect chunking settings**: Check `self.chunk` before chunking
4. **Add meaningful metadata**: Include source info in `meta_data`
5. **Document dependencies**: If your reader requires optional packages, document them
6. **Use lazy imports**: Import heavy dependencies inside methods, not at module level

## Example: Complete Reader

See these existing readers for reference:
- `pdf_reader.py` - File-based reader with OCR support
- `website_reader.py` - URL-based reader with HTML parsing
- `csv_reader.py` - Tabular data reader with row chunking
- `youtube_reader.py` - API-based reader for external services
