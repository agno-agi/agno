# Test Log — chunking

Tested: 2026-02-12 | Branch: cookbook/v25-merge-fixes

| File | Status | Notes |
|------|--------|-------|
| agentic_chunking.py | PASS | AI-driven chunking with LLM, answered recipe questions correctly |
| code_chunking.py | FAIL | Error: No module named 'tree_sitter_language_pack' |
| code_chunking_custom_tokenizer.py | FAIL | Error: No module named 'tree_sitter_language_pack' |
| csv_row_chunking.py | FAIL | Timeout: embedding 1000 IMDB rows exceeds 120s limit |
| custom_strategy_example.py | PASS | Custom chunking strategy ran correctly |
| document_chunking.py | PASS | Document-level chunking, detailed recipe responses |
| fixed_size_chunking.py | PASS | Fixed-size character chunking worked correctly |
| markdown_chunking.py | SKIP | Missing: unstructured package |
| recursive_chunking.py | PASS | Recursive hierarchical chunking worked correctly |
| semantic_chunking.py | PASS | Semantic boundary detection with OpenAI embedder |
| semantic_chunking_agno_embedder.py | PASS | Semantic chunking with Agno GeminiEmbedder |
| semantic_chunking_chonkie_embedder.py | PASS | Semantic chunking with chonkie GeminiEmbeddings |

## Summary

| Status | Count |
|--------|-------|
| PASS   | 8     |
| FAIL   | 3     |
| SKIP   | 1     |

FAIL: code_chunking.py, code_chunking_custom_tokenizer.py (tree_sitter_language_pack), csv_row_chunking.py (timeout)
SKIP: markdown_chunking.py (unstructured package)
