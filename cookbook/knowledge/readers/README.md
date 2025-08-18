# Readers

Readers transform raw data into structured, searchable knowledge that powers your agents.

Document readers enable your agents to learn from:
- **Structured documents** (PDFs, Word docs, presentations)
- **Web content** (websites, APIs, online databases)
- **Data files** (CSV, JSON, XML)
- **Research sources** (ArXiv papers, academic databases)
- **Real-time feeds** (news, social media, RSS)

## Core Concepts

| Concept | Description |
|---------|-------------|
| **Document Reader** | Components that read and process different file formats |
| **PDF Reader** | Reads PDF documents and extracts text content |
| **CSV Reader** | Processes CSV files and converts rows to documents |
| **ArXiv Reader** | Fetches research papers from ArXiv by topic |
| **Async Processing** | Non-blocking document processing for large datasets |

## Getting Started

### 1. Setup Knowledge Base

```python
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.pgvector import PgVector

knowledge = Knowledge(
    vector_db=PgVector(
        table_name="documents",
        db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
    )
)
```

### 2. CSV Reader

```python
from agno.knowledge.reader.csv_reader import CSVReader

reader = CSVReader()
documents = reader.read("tmp/test.csv")

for doc in documents:
    print(f"Document: {doc.name}")
    print(f"Content length: {len(doc.content)}")
```

### 3. PDF Reader (Async)

```python
import asyncio

# Add PDFs asynchronously
await knowledge.async_add_content(path="data/pdf")
```

### 4. ArXiv Reader

```python
from agno.knowledge.reader.arxiv_reader import ArxivReader

knowledge.add_content(
    topics=["Generative AI", "Machine Learning"],
    reader=ArxivReader(),
)
```

## Examples

- **csv_reader.py** - Read CSV files and extract documents
- **pdf_reader_async.py** - Async PDF processing with agent integration  
- **arxiv_reader.py** - Fetch research papers from ArXiv

### Processing Pipeline

```python
# Standard reader pipeline: Source → Reader → Chunking → Embedding → Storage
source_content → reader.extract() → chunking_strategy.chunk() → embedder.embed() → vector_db.store()
```

## Document Readers

### 1. PDF Reader (`pdf_reader_async.py`)

**When to use**: Processing PDF documents, reports, manuals, and academic papers.

**Features**:
- OCR support for scanned documents
- Table and image extraction
- Metadata preservation
- Multi-page processing

```python
import asyncio
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.pdf_reader import PDFUrlReader, PDFReader
from agno.vectordb.pgvector import PgVector

# Async PDF processing for better performance
async def process_pdf_documents():
    knowledge = Knowledge(
        vector_db=PgVector(table_name="pdf_documents", db_url=db_url)
    )
    
    # Process PDF from URL
    await knowledge.async_add_content(
        url="https://example.com/document.pdf",
        reader=PDFUrlReader(
            extract_images=True,
            extract_tables=True
        )
    )
    
    # Process local PDF files
    await knowledge.async_add_content(
        path="documents/",
        reader=PDFReader(
            extract_metadata=True,
            chunk_size=1000
        )
    )

# Run async processing
asyncio.run(process_pdf_documents())
```

**Best practices**:
- Use async processing for large PDF collections
- Enable OCR for scanned documents
- Extract tables and images for comprehensive understanding
- Set appropriate chunk sizes based on document structure

### 2. Web Content Readers (`web_reader.py`, `url_reader.py`)

**When to use**: Extracting content from websites, blogs, documentation, and online resources.

**Web Reader** - Advanced web scraping with JavaScript support:
```python
from agno.knowledge.reader.web_reader import WebReader

web_reader = WebReader(
    max_links=50,           # Maximum links to follow
    max_depth=2,            # Crawling depth
    wait_time=1,            # Delay between requests
    extract_images=True,    # Extract image descriptions
    follow_redirects=True   # Handle redirects
)

knowledge.add_content(
    url="https://docs.example.com",
    reader=web_reader,
    metadata={"source": "documentation", "type": "technical_docs"}
)
```

**URL Reader** - Simple, fast URL content extraction:
```python
from agno.knowledge.reader.url_reader import URLReader

url_reader = URLReader(
    timeout=30,
    headers={"User-Agent": "AgnoBot/1.0"}
)

# Process multiple URLs
urls = [
    "https://blog.example.com/post1",
    "https://blog.example.com/post2", 
    "https://news.example.com/article"
]

for url in urls:
    knowledge.add_content(
        url=url,
        reader=url_reader,
        metadata={"source": "blog", "extracted_at": datetime.now().isoformat()}
    )
```

### 3. Firecrawl Reader (`firecrawl_reader.py`)

**When to use**: Professional web scraping with advanced JavaScript rendering and anti-bot protection.

**Features**:
- JavaScript-heavy site support
- Anti-bot detection bypass
- Structured data extraction
- Rate limiting and proxy support

```python
from agno.knowledge.reader.firecrawl_reader import FirecrawlReader

firecrawl_reader = FirecrawlReader(
    api_key="your_firecrawl_api_key",
    formats=["markdown", "html"],
    only_main_content=True,
    include_tags=["title", "meta", "headers"]
)

# Scrape complex JavaScript applications
knowledge.add_content(
    url="https://app.example.com/dashboard",
    reader=firecrawl_reader,
    metadata={"source": "web_app", "requires_js": True}
)
```

### 4. CSV Data Reader (`csv_reader.py`, `csv_reader_async.py`)

**When to use**: Processing structured data, databases exports, and tabular information.

**Synchronous CSV processing**:
```python
from agno.knowledge.reader.csv_reader import CSVReader

csv_reader = CSVReader(
    delimiter=",",
    encoding="utf-8",
    has_header=True,
    columns_to_index=["product_name", "description", "category"]
)

knowledge.add_content(
    path="data/products.csv",
    reader=csv_reader,
    metadata={"source": "product_catalog", "format": "csv"}
)
```

**Asynchronous CSV processing** (`csv_reader_async.py`):
```python
import asyncio
from agno.knowledge.reader.csv_reader import AsyncCSVReader

async def process_csv_files():
    csv_reader = AsyncCSVReader(
        batch_size=1000,        # Process in batches
        parallel_chunks=4       # Parallel processing
    )
    
    # Process large CSV files efficiently
    await knowledge.async_add_content(
        path="data/large_dataset.csv",
        reader=csv_reader
    )

asyncio.run(process_csv_files())
```

**CSV from URL** (`csv_reader_url_async.py`):
```python
# Process CSV files directly from URLs
await knowledge.async_add_content(
    url="https://data.example.com/dataset.csv",
    reader=AsyncCSVReader(
        download_timeout=60,
        streaming=True  # For very large files
    )
)
```

### 5. JSON Reader (`json_reader.py`)

**When to use**: Processing API responses, configuration files, and structured JSON data.

```python
from agno.knowledge.reader.json_reader import JSONReader

json_reader = JSONReader(
    extract_nested=True,        # Handle nested objects
    flatten_arrays=False,       # Keep array structure
    max_depth=5,                # Limit recursion depth
    include_metadata=True       # Preserve JSON structure info
)

# Process JSON API responses
knowledge.add_content(
    url="https://api.example.com/products",
    reader=json_reader,
    metadata={"source": "api", "endpoint": "products"}
)

# Process local JSON files
knowledge.add_content(
    path="config/",
    reader=json_reader,
    metadata={"source": "configuration"}
)
```

### 6. Markdown Reader (`markdown_reader_async.py`)

**When to use**: Processing documentation, README files, and markdown-based content.

```python
import asyncio
from agno.knowledge.reader.markdown_reader import AsyncMarkdownReader

async def process_markdown_docs():
    md_reader = AsyncMarkdownReader(
        parse_headers=True,         # Extract header hierarchy
        extract_code_blocks=True,   # Separate code from text
        preserve_formatting=True,   # Keep markdown formatting
        extract_links=True          # Extract and verify links
    )
    
    # Process documentation repository
    await knowledge.async_add_content(
        path="docs/",
        reader=md_reader,
        metadata={"source": "documentation", "format": "markdown"}
    )

asyncio.run(process_markdown_docs())
```

### 7. ArXiv Research Reader (`arxiv_reader.py`, `arxiv_reader_async.py`)

**When to use**: Building research knowledge bases with academic papers and scientific literature.

**Synchronous ArXiv processing**:
```python
from agno.knowledge.reader.arxiv_reader import ArXivReader

arxiv_reader = ArXivReader(
    max_results=100,
    sort_by="relevance",        # or "lastUpdatedDate", "submittedDate"
    sort_order="descending",
    extract_citations=True,     # Extract reference information
    download_pdf=True           # Download full PDFs
)

# Search and process papers by topic
knowledge.add_content(
    query="machine learning transformers",
    reader=arxiv_reader,
    metadata={"source": "arxiv", "topic": "ml_transformers"}
)

# Process specific papers by ArXiv ID
knowledge.add_content(
    arxiv_ids=["2106.04554", "1706.03762"],  # Specific paper IDs
    reader=arxiv_reader,
    metadata={"source": "arxiv", "collection": "selected_papers"}
)
```

**Asynchronous ArXiv processing** (`arxiv_reader_async.py`):
```python
import asyncio
from agno.knowledge.reader.arxiv_reader import AsyncArXivReader

async def build_research_knowledge_base():
    arxiv_reader = AsyncArXivReader(
        concurrent_downloads=5,     # Parallel PDF downloads
        retry_attempts=3,
        timeout=120
    )
    
    # Research topics to process
    research_topics = [
        "natural language processing",
        "computer vision",
        "reinforcement learning",
        "neural networks"
    ]
    
    # Process multiple topics concurrently
    tasks = []
    for topic in research_topics:
        task = knowledge.async_add_content(
            query=topic,
            reader=arxiv_reader,
            metadata={"source": "arxiv", "topic": topic.replace(" ", "_")}
        )
        tasks.append(task)
    
    await asyncio.gather(*tasks)

asyncio.run(build_research_knowledge_base())
```

### 8. Document Knowledge Base (`doc_kb_async.py`)

**When to use**: Building comprehensive knowledge bases from multiple document sources.

```python
import asyncio
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.document_reader import DocumentReader

async def create_comprehensive_knowledge_base():
    """Create knowledge base from multiple document types"""
    
    knowledge = Knowledge(
        vector_db=PgVector(table_name="comprehensive_docs", db_url=db_url)
    )
    
    # Document sources with different readers
    document_sources = [
        {
            "path": "pdfs/",
            "reader": PDFReader(extract_tables=True),
            "metadata": {"type": "pdf", "category": "reports"}
        },
        {
            "path": "docs/",
            "reader": MarkdownReader(parse_headers=True),
            "metadata": {"type": "markdown", "category": "documentation"}
        },
        {
            "url": "https://api.company.com/knowledge",
            "reader": JSONReader(extract_nested=True),
            "metadata": {"type": "json", "category": "api_docs"}
        }
    ]
    
    # Process all sources asynchronously
    tasks = []
    for source in document_sources:
        if "path" in source:
            task = knowledge.async_add_content(
                path=source["path"],
                reader=source["reader"],
                metadata=source["metadata"]
            )
        else:
            task = knowledge.async_add_content(
                url=source["url"],
                reader=source["reader"],
                metadata=source["metadata"]
            )
        tasks.append(task)
    
    await asyncio.gather(*tasks)
    
    return knowledge

# Create comprehensive knowledge base
knowledge_base = asyncio.run(create_comprehensive_knowledge_base())
```

## Common Issues and Solutions

**Problem**: Large PDF files causing memory issues
**Solution**: Use streaming PDF readers, process in chunks, increase memory allocation

**Problem**: Web scraping blocked by anti-bot measures
**Solution**: Use Firecrawl reader, implement delays, rotate user agents

**Problem**: Inconsistent CSV formats
**Solution**: Implement format detection, use flexible CSV readers, validate data

**Problem**: Poor text extraction quality from scanned PDFs
**Solution**: Enable OCR processing, use specialized OCR tools, preprocess images

**Problem**: Slow processing of large document collections
**Solution**: Use async readers, batch processing, parallel execution, optimize chunk sizes
