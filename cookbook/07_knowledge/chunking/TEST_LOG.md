# TEST_LOG

## chunking — v2.5 Review

Tested: 2026-02-11 | Branch: cookbooks/v2.5-testing

---

### agentic_chunking.py

**Status:** PASS

**Description:** AI-driven chunking using AgenticChunking strategy with PDFReader. Uses LLM to determine chunk boundaries.

**Result:** Successfully chunked Thai recipes PDF using LLM-driven boundaries. Agent answered recipe questions correctly.

---

### code_chunking.py

**Status:** FAIL

**Description:** Specialized chunking for source code using CodeChunking with TextReader.

**Result:** ImportError — `chonkie` package not installed. Requires `pip install "chonkie[code]"`. Not a v2.5 regression.

---

### code_chunking_custom_tokenizer.py

**Status:** FAIL

**Description:** Custom tokenizer implementation for code chunking using chonkie Tokenizer ABC.

**Result:** ImportError — `chonkie` package not installed. Same dependency as code_chunking.py.

---

### csv_row_chunking.py

**Status:** FAIL

**Description:** Row-based chunking for CSV files using RowChunking with CSVReader.

**Result:** ImportError — `aiofiles` package not installed. CSVReader requires aiofiles for async file operations. Not a v2.5 regression.

---

### custom_strategy_example.py

**Status:** PASS

**Description:** Template for custom chunking strategy inheriting ChunkingStrategy ABC. Implements chunk(document) method with metadata preservation.

**Result:** Successfully created custom strategy, chunked PDF, and agent answered questions about Thai recipes.

---

### document_chunking.py

**Status:** PASS

**Description:** Document-level chunking (entire documents as chunks) using DocumentChunking with PDFReader.

**Result:** Successfully treated each PDF page as a single chunk. Agent answered recipe questions with detailed ingredients and directions.

---

### fixed_size_chunking.py

**Status:** PASS

**Description:** Fixed-size character/token chunking using FixedSizeChunking with PDFReader.

**Result:** Successfully split PDF into fixed-size chunks. Agent answered recipe questions correctly.

---

### markdown_chunking.py

**Status:** FAIL

**Description:** Markdown-aware heading-based chunking with 5 strategy variants using MarkdownChunking.

**Result:** ImportError — `unstructured` package not installed. Requires `pip install unstructured markdown`. Not a v2.5 regression.

---

### recursive_chunking.py

**Status:** PASS

**Description:** Recursive hierarchical chunking using RecursiveChunking with PDFReader.

**Result:** Successfully split PDF into recursive chunks. Agent answered recipe questions with detailed Massaman curry recipe.

---

### semantic_chunking.py

**Status:** FAIL

**Description:** AI-powered semantic boundary detection using SemanticChunking with OpenAI embedder.

**Result:** ImportError — `chonkie` package not installed. Requires `pip install "chonkie[semantic]"`. Not a v2.5 regression.

---

### semantic_chunking_agno_embedder.py

**Status:** FAIL

**Description:** Semantic chunking with Agno GeminiEmbedder instead of chonkie embedder.

**Result:** ImportError — `chonkie` package not installed. SemanticChunking strategy requires chonkie regardless of embedder choice.

---

### semantic_chunking_chonkie_embedder.py

**Status:** FAIL

**Description:** Semantic chunking with separate chonkie GeminiEmbeddings for chunking and Agno GeminiEmbedder for VectorDB.

**Result:** ImportError — `chonkie` package not installed.

---

## Summary

| Status | Count | Files |
|--------|-------|-------|
| PASS   | 4     | agentic_chunking, custom_strategy_example, document_chunking, fixed_size_chunking, recursive_chunking |
| FAIL   | 7     | code_chunking (chonkie), code_chunking_custom_tokenizer (chonkie), csv_row_chunking (aiofiles), markdown_chunking (unstructured), semantic_chunking (chonkie), semantic_chunking_agno_embedder (chonkie), semantic_chunking_chonkie_embedder (chonkie) |

No v2.5 regressions detected. All failures are missing optional dependencies (chonkie, aiofiles, unstructured).
