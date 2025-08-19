# Text Chunking

Chunking breaks down large documents into manageable pieces for efficient knowledge retrieval. The strategy you choose directly impacts your agent's ability to find and use relevant information.


When building knowledge bases, chunking is critical because:
- **Vector databases** work best with appropriately sized text segments
- **LLM context windows** have limits on input size
- **Retrieval quality** depends on semantic coherence within chunks

## Setup

```bash
pip install agno openai
```

Set your OpenAI API key:
```bash
export OPENAI_API_KEY=your_api_key
```

## Chunking Strategy Selection

| Strategy | Best For | Chunk Size |
|----------|----------|------------|
| **Agentic** | Complex documents | Variable |
| **Semantic** | Topic coherence | Variable |
| **Fixed Size** | Consistent processing | Fixed |
| **Recursive** | Nested structures | Hierarchical |
| **Document** | Boundary preservation | Document-based |
| **CSV Row** | Structured data | Row-based |

## Chunking Strategies

### 1. Agentic Chunking (`agentic_chunking.py`)

**How it works**: Uses AI to determine optimal chunk boundaries based on content understanding, context, and semantic flow.

```python
from agno.knowledge.chunking.agentic import AgenticChunking
from agno.knowledge.reader.pdf_reader import PDFUrlReader

reader = PDFUrlReader(
    chunking_strategy=AgenticChunking(),
)
```

**Best practices**:
- Use for research papers, legal documents, technical manuals
- Higher processing cost but better semantic coherence
- Ideal when chunk quality is more important than speed

### 2. Semantic Chunking (`semantic_chunking.py`)

**How it works**: Groups sentences based on semantic similarity, ensuring related content stays together.

```python
from agno.knowledge.chunking.semantic import SemanticChunking

chunking_strategy = SemanticChunking(similarity_threshold=0.5)
```

**Configuration**:
- `similarity_threshold`: Controls chunk boundary sensitivity (0.3-0.8)
- Lower values = smaller, more focused chunks
- Higher values = larger, more comprehensive chunks

### 3. Fixed Size Chunking (`fixed_size_chunking.py`)

**How it works**: Splits text into chunks of specified character or token length with optional overlap.

```python
from agno.knowledge.chunking.fixed import FixedSizeChunking

chunking_strategy = FixedSizeChunking(
    chunk_size=1000,
    overlap=100
)
```

**Best practices**:
- Start with 500-1500 characters for most use cases
- Use 10-20% overlap to preserve context at boundaries

### 4. Recursive Chunking (`recursive_chunking.py`)

**How it works**: Attempts to split on natural boundaries (paragraphs, sentences) before falling back to character limits.

**Best practices**:
- Ideal for structured documents (reports, documentation)
- Preserves document hierarchy and formatting

### 5. Document Chunking (`document_chunking.py`)

**How it works**: Treats each document as a single chunk, maintaining full context and document-level metadata.

**Best practices**:
- Use for short documents (< 2000 tokens)
- When document-level context is crucial
- Ideal for emails, articles, short reports

### 6. CSV Row Chunking (`csv_row_chunking.py`)

**How it works**: Each CSV row becomes a separate chunk with preserved column structure.

**Best practices**:
- Perfect for product catalogs, customer data, inventory
- Maintains data relationships and structure
- Enables precise filtering and retrieval

## Optimization Tips

```python
# For better retrieval, combine strategies
knowledge = Knowledge(
    vector_db=PgVector(table_name="mixed_chunking", db_url=db_url),
)

# Technical docs with semantic chunking
knowledge.add_content(
    url="technical_manual.pdf",
    reader=PDFUrlReader(chunking_strategy=SemanticChunking(similarity_threshold=0.6))
)

# FAQ with document chunking (one chunk per FAQ)
knowledge.add_content(
    path="faq/",
    reader=DocumentReader(chunking_strategy=DocumentChunking())
)
```

### Testing Different Strategies

```python
# Compare chunking strategies for your specific content
strategies = [
    ("semantic", SemanticChunking(similarity_threshold=0.5)),
    ("fixed", FixedSizeChunking(chunk_size=1000, overlap=100)),
    ("agentic", AgenticChunking()),
]

for name, strategy in strategies:
    knowledge = Knowledge(
        vector_db=PgVector(table_name=f"test_{name}", db_url=db_url),
    )
    knowledge.add_content(url="test_document.pdf", reader=PDFUrlReader(chunking_strategy=strategy))
    # Test retrieval quality with your typical queries
```