# Text Chunking

Chunking breaks down large documents into manageable pieces for efficient knowledge retrieval and processing in databases.

## Setup

```bash
pip install agno openai
```

Set your OpenAI API key:

```bash
export OPENAI_API_KEY=your_api_key
```

## Basic Integration

Chunking strategies integrate with readers to process documents:

```python
from agno.knowledge.reader.pdf_reader import PDFReader
from agno.knowledge.chunking.semantic import SemanticChunking

reader = PDFReader(
    chunking_strategy=SemanticChunking()
)
knowledge.add_content(url="document.pdf", reader=reader)

agent = Agent(
    knowledge=knowledge_base,
    search_knowledge=True,
)

agent.print_response(
    "What are the key concepts covered in this document?",
    markdown=True
)
```

## Implementing Your Own Chunking Strategy

You can implement custom chunking strategies by inheriting from `ChunkingStrategy` and implementing the `chunk()` method. This allows you to create domain-specific chunking logic tailored to your content and use cases.

See the [custom strategy example](./custom_strategy_example.py) for a complete walkthrough.

## Supported Chunking Strategies

- **[Agentic Chunking](./agentic_chunking.py)** - AI-powered intelligent chunk boundaries
- **[CSV Row Chunking](./csv_row_chunking.py)** - Each CSV row as a separate chunk
- **[Document Chunking](./document_chunking.py)** - Treat entire document as single chunk
- **[Fixed Size Chunking](./fixed_size_chunking.py)** - Fixed character/token length chunks
- **[Recursive Chunking](./recursive_chunking.py)** - Natural boundary-aware chunking
- **[Semantic Chunking](./semantic_chunking.py)** - Semantically coherent chunks
- **[Custom Strategy Example](./custom_strategy_example.py)** - Learn how to implement your own chunking strategy
