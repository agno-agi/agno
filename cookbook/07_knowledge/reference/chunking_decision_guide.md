# Chunking Strategy Decision Guide

How to choose the right chunking strategy for your content.

## Decision Tree

1. **Is your content source code?** -> Use Code Chunking
2. **Is your content Markdown with headers?** -> Use Markdown Chunking
3. **Is your content structured (CSV, JSON)?** -> Use Row Chunking
4. **Do you need the highest quality?** -> Use Agentic Chunking (slowest)
5. **Is your document mixed-topic?** -> Use Semantic Chunking
6. **Do you want a good default?** -> Use Recursive Chunking
7. **Do you want simplicity?** -> Use Fixed Size Chunking

## Strategy Comparison

| Strategy | Best For | Speed | Quality | Chunk Size Control |
|----------|----------|-------|---------|-------------------|
| Fixed Size | Any text, simplicity | Fast | Low | Exact |
| Recursive | General text, good default | Fast | Medium | Approximate |
| Semantic | Mixed-topic documents | Medium | High | Variable |
| Document | Multi-page PDFs, reports | Fast | Medium | Page-based |
| Markdown | Documentation, READMEs | Fast | High | Header-based |
| Code | Source code files | Fast | High | Function/class-based |
| Agentic | Any text, highest quality | Slow | Highest | LLM-determined |
| Row | CSV, tabular data | Fast | N/A | Row-based |

## Chunk Size Guidelines

- **Too small** (< 100 chars): Chunks lose context, poor retrieval
- **Sweet spot** (300-1000 chars): Good balance of context and precision
- **Too large** (> 2000 chars): Chunks contain too much noise, diluted relevance

## Configuration Examples

```python
from agno.knowledge.chunking.fixed import FixedSizeChunking
from agno.knowledge.chunking.recursive import RecursiveChunking
from agno.knowledge.chunking.semantic import SemanticChunking

# Fixed: predictable sizes
FixedSizeChunking(chunk_size=500)

# Recursive: respects natural boundaries
RecursiveChunking(chunk_size=500, overlap=50)

# Semantic: groups by meaning
SemanticChunking(embedder=OpenAIEmbedder(id="text-embedding-3-small"))
```

## When to Start

Start with **Recursive Chunking** (chunk_size=500). It works well for most content.
Only switch strategies if retrieval quality is poor for your specific use case.
