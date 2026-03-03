# Knowledge & RAG System

Agno's `Knowledge` class provides plug-and-play Retrieval-Augmented Generation (RAG). It handles ingestion, chunking, embedding, storage, and retrieval automatically.

**File:** `libs/agno/agno/knowledge/knowledge.py` (3,501 lines)

---

## Architecture

```
Source Documents
      ↓
  [Readers]     ← convert files/URLs/cloud to Document objects
      ↓
  [Chunkers]    ← split into chunks with overlap
      ↓
  [Embedders]   ← convert text to vectors
      ↓
 [VectorDB]     ← store indexed chunks
      ↓
  [Retrieval]   ← similarity search at query time
      ↓
  [Rerankers]   ← optional: re-rank results by relevance
      ↓
Context injection into agent system prompt
```

---

## Quick start

```python
from agno.knowledge import Knowledge
from agno.vectordb.pgvector import PgVector
from agno.embedder.openai import OpenAIEmbedder
from agno.knowledge.reader.pdf import PDFReader
from agno.agent import Agent
from agno.models.openai import OpenAIChat

knowledge = Knowledge(
    sources=[PDFReader(path="./docs/")],
    vector_db=PgVector(
        table_name="docs",
        db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)
knowledge.load()  # ingest and index all sources

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    knowledge=knowledge,
    search_knowledge=True,  # let agent decide when to search
)
agent.print_response("What are the key points in the product spec?")
```

---

## Document readers (20+)

Readers convert raw sources into `Document` objects.

### File-based readers

| Reader | Import | Handles |
|--------|--------|---------|
| `PDFReader` | `agno.knowledge.reader.pdf` | PDF files (local or URL) |
| `DocxReader` | `agno.knowledge.reader.docx` | Microsoft Word `.docx` |
| `ExcelReader` | `agno.knowledge.reader.excel` | Excel `.xlsx` / `.xls` |
| `CSVReader` | `agno.knowledge.reader.csv_reader` | CSV data files |
| `PPTXReader` | `agno.knowledge.reader.pptx` | PowerPoint presentations |
| `MarkdownReader` | `agno.knowledge.reader.markdown` | Markdown `.md` files |
| `TextReader` | `agno.knowledge.reader.text` | Plain text `.txt` |
| `JSONReader` | `agno.knowledge.reader.json` | JSON files |

```python
from agno.knowledge.reader.pdf import PDFReader
from agno.knowledge.reader.docx import DocxReader

knowledge = Knowledge(
    sources=[
        PDFReader(path="./manuals/"),      # all PDFs in directory
        DocxReader(path="./contracts/"),   # all Word docs
    ],
    vector_db=vdb,
)
```

### Web-based readers

| Reader | Import | Handles |
|--------|--------|---------|
| `WebsiteReader` | `agno.knowledge.reader.website` | Scrape web pages |
| `WebSearchReader` | `agno.knowledge.reader.web_search` | Web search results |
| `TavilyReader` | `agno.knowledge.reader.tavily` | Tavily API content |
| `FirecrawlReader` | `agno.knowledge.reader.firecrawl` | Firecrawl API |

```python
from agno.knowledge.reader.website import WebsiteReader

knowledge = Knowledge(
    sources=[
        WebsiteReader(
            urls=["https://docs.example.com/"],
            max_links=50,          # follow up to 50 internal links
            max_depth=3,           # crawl 3 levels deep
        )
    ],
    vector_db=vdb,
)
```

### Data-source readers

| Reader | Import | Handles |
|--------|--------|---------|
| `ArxivReader` | `agno.knowledge.reader.arxiv` | ArXiv papers by ID or query |
| `WikipediaReader` | `agno.knowledge.reader.wikipedia` | Wikipedia articles |
| `YoutubeReader` | `agno.knowledge.reader.youtube` | YouTube transcripts |
| `S3Reader` | `agno.knowledge.reader.s3` | AWS S3 file contents |

### Auto-detection

```python
from agno.knowledge.reader.factory import ReaderFactory

# Automatically picks the right reader based on file extension / URL
reader = ReaderFactory.get_reader("./report.pdf")
```

---

## Cloud storage loaders

Load entire cloud storage buckets/containers as knowledge sources.

| Loader | Import | Source |
|--------|--------|--------|
| `S3Loader` | `agno.knowledge.loaders.s3` | AWS S3 bucket |
| `GCSLoader` | `agno.knowledge.loaders.gcs` | Google Cloud Storage bucket |
| `AzureBlobLoader` | `agno.knowledge.loaders.azure_blob` | Azure Blob Storage container |
| `SharePointLoader` | `agno.knowledge.loaders.sharepoint` | Microsoft SharePoint library |
| `GitHubLoader` | `agno.knowledge.loaders.github` | GitHub repository |

```python
from agno.knowledge.loaders.s3 import S3Loader

knowledge = Knowledge(
    sources=[
        S3Loader(
            bucket="my-company-docs",
            prefix="engineering/",
            filters=["*.pdf", "*.md"],
        )
    ],
    vector_db=vdb,
)
```

---

## Chunking strategies (8)

Chunking splits documents into pieces before embedding.

| Strategy | Import | Best for |
|----------|--------|---------|
| `RecursiveChunker` | `agno.knowledge.chunking.recursive` | General text — default choice |
| `FixedChunker` | `agno.knowledge.chunking.fixed` | Uniform chunks, simple use cases |
| `SemanticChunker` | `agno.knowledge.chunking.semantic` | LLM-guided semantic boundaries |
| `MarkdownChunker` | `agno.knowledge.chunking.markdown` | Markdown docs — respects headings |
| `CodeChunker` | `agno.knowledge.chunking.code` | Code files — respects functions/classes |
| `DocumentChunker` | `agno.knowledge.chunking.document` | Preserves document-level structure |
| `RowChunker` | `agno.knowledge.chunking.row` | Row-based data (CSV, tables) |
| `AgenticChunker` | `agno.knowledge.chunking.agentic` | LLM decides chunk boundaries |

```python
from agno.knowledge.chunking.recursive import RecursiveChunker
from agno.knowledge.chunking.semantic import SemanticChunker

# Recursive (default — fast, good quality)
chunker = RecursiveChunker(chunk_size=1000, chunk_overlap=200)

# Semantic (slower, best quality — uses LLM)
chunker = SemanticChunker(model=OpenAIChat(id="gpt-4o-mini"))

knowledge = Knowledge(sources=[...], vector_db=vdb, chunking_strategy=chunker)
```

---

## Embedder providers (18)

| Provider | Import |
|----------|--------|
| OpenAI | `agno.embedder.openai.OpenAIEmbedder` |
| Cohere | `agno.embedder.cohere.CohereEmbedder` |
| Google Gemini | `agno.embedder.google.GeminiEmbedder` |
| Mistral | `agno.embedder.mistral.MistralEmbedder` |
| Ollama | `agno.embedder.ollama.OllamaEmbedder` |
| HuggingFace | `agno.embedder.huggingface.HuggingfaceCustomEmbedder` |
| Sentence Transformers | `agno.embedder.sentence_transformer.SentenceTransformerEmbedder` |
| Jina | `agno.embedder.jina.JinaEmbedder` |
| VoyageAI | `agno.embedder.voyageai.VoyageAIEmbedder` |
| AWS Bedrock | `agno.embedder.aws_bedrock.AwsBedrockEmbedder` |
| Azure OpenAI | `agno.embedder.azure_openai.AzureOpenAIEmbedder` |
| Together | `agno.embedder.together.TogetherEmbedder` |
| Fireworks | `agno.embedder.fireworks.FireworksEmbedder` |

```python
from agno.embedder.ollama import OllamaEmbedder  # local, no API key

vdb = ChromaDb(
    collection="docs",
    embedder=OllamaEmbedder(id="nomic-embed-text"),
)
```

---

## Rerankers

After vector search, rerankers re-order results by relevance before injection:

```python
from agno.knowledge.reranker.cohere import CohereReranker

knowledge = Knowledge(
    sources=[...],
    vector_db=vdb,
    reranker=CohereReranker(model="rerank-english-v3.0", top_n=5),
)
```

---

## Metadata filtering

Filter knowledge results by metadata attached to documents:

```python
from agno.filters import Filter

# Only retrieve documents tagged as "public"
knowledge.search(
    query="product pricing",
    filters=Filter.eq("access_level", "public") & Filter.eq("department", "sales"),
)
```

Available filter operators: `eq`, `ne`, `gt`, `gte`, `lt`, `lte`, `in_`, `nin`, `and_`, `or_`, `not_`

---

## Knowledge modes

### Agent searches knowledge (agentic RAG)

```python
agent = Agent(
    knowledge=knowledge,
    search_knowledge=True,   # agent calls `search_knowledge` tool when needed
)
```

### Knowledge always injected (always-on RAG)

```python
agent = Agent(
    knowledge=knowledge,
    add_references=True,       # inject top-k results into every prompt
    num_documents=5,           # how many chunks to inject
)
```

---

## Loading and updating

```python
# Initial load — ingest all sources
knowledge.load()

# Add new documents incrementally (no full rebuild)
knowledge.load_text("New policy document: ...", metadata={"doc_id": "pol-2025"})
knowledge.load_document(Document(content="...", meta_data={"source": "wiki"}))

# Rebuild from scratch (drop + re-index)
knowledge.load(recreate=True)
```

---

## FileSystemKnowledge — shorthand for local files

```python
from agno.knowledge import FileSystemKnowledge

knowledge = FileSystemKnowledge(
    path="./docs/",           # recursively loads all supported file types
    vector_db=vdb,
    num_documents=5,
)
```

---

## Example: Full RAG pipeline

```python
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.knowledge import Knowledge
from agno.knowledge.reader.pdf import PDFReader
from agno.knowledge.reader.website import WebsiteReader
from agno.knowledge.chunking.recursive import RecursiveChunker
from agno.vectordb.pgvector import PgVector
from agno.embedder.openai import OpenAIEmbedder

knowledge = Knowledge(
    sources=[
        PDFReader(path="./manuals/"),
        WebsiteReader(urls=["https://support.example.com/"], max_links=100),
    ],
    vector_db=PgVector(
        table_name="support_kb",
        db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
        search_type="hybrid",
    ),
    chunking_strategy=RecursiveChunker(chunk_size=800, chunk_overlap=100),
    num_documents=6,
)
knowledge.load()

support_agent = Agent(
    name="Support Agent",
    model=OpenAIChat(id="gpt-4o"),
    knowledge=knowledge,
    search_knowledge=True,
    instructions=[
        "You are a customer support agent.",
        "Always search the knowledge base before answering.",
        "Cite the source document when referencing information.",
    ],
)

support_agent.print_response("How do I reset my password?")
```
