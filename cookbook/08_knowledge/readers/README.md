# Readers

Readers transform raw data into structured, searchable knowledge for your agents. Agno supports multiple document types and data sources.

## Basic Integration

Readers integrate with the Knowledge system to process different data sources:

```python
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.pdf_reader import PDFReader

knowledge = Knowledge(vector_db=your_vector_db)
knowledge.add_content(
    path="documents/",
    reader=PDFReader(),
    metadata={"source": "docs"}
)

agent = Agent(
    knowledge=knowledge,
    search_knowledge=True,
)
```

## Supported Readers

- **[ArXiv](./arxiv_reader.py)** - Academic papers from ArXiv
- **[ArXiv Async](./arxiv_reader_async.py)** - Asynchronous ArXiv processing
- **[CSV](./csv_reader.py)** - Comma-separated value files
- **[CSV Async](./csv_reader_async.py)** - Asynchronous CSV processing
- **[CSV from URL Async](./csv_reader_url_async.py)** - CSV files from URLs
- **[Document Knowledge Base](./doc_kb_async.py)** - Multiple document sources
- **[Firecrawl](./firecrawl_reader.py)** - Advanced web scraping
- **[JSON](./json_reader.py)** - JSON data and API responses
- **[Markdown Async](./markdown_reader_async.py)** - Markdown documentation
- **[PDF Async](./pdf_reader_async.py)** - PDF documents with OCR
- **[PPTX](./pptx_reader.py)** - PowerPoint presentation files
- **[PPTX Async](./pptx_reader_async.py)** - Asynchronous PowerPoint processing
- **[Web](./web_reader.py)** - Website crawling and scraping
- 
