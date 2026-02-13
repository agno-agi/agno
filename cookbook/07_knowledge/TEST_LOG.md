# Test Log — 07_knowledge (Root)

Tested: 2026-02-12 | Branch: cookbook/v25-merge-fixes

## Root-Level Files

| File | Status | Notes |
|------|--------|-------|
| quickstart.py | PASS | Quick demo loading docs.agno.com, agent answered about Agno |
| knowledge_tools.py | FAIL | Timeout: downloading docs.agno.com/llms-full.txt exceeds 120s |

## Subdirectory Summary

| Subdirectory | PASS | FAIL | SKIP | Total |
|-------------|------|------|------|-------|
| 01_quickstart | 16 | 0 | 1 | 17 |
| basic_operations | - | - | - | 0 (no .py files) |
| chunking | 8 | 3 | 1 | 12 |
| cloud | 0 | 0 | 4 | 4 |
| custom_retriever | 1 | 0 | 2 | 3 |
| embedders | 1 | 0 | 18 | 19 |
| filters | 10 | 0 | 8 | 18 |
| os | 0 | 0 | 1 | 1 |
| protocol | 1 | 0 | 0 | 1 |
| readers | 20 | 4 | 1 | 25 |
| search_type | 3 | 0 | 0 | 3 |
| vector_db | 2 | 0 | 30 | 32 |

## Grand Total

| Status | Count |
|--------|-------|
| **PASS** | **63** |
| **FAIL** | **8** |
| **SKIP** | **66** |
| **Total** | **137** |

## Notable Failures

- **knowledge_tools.py**: Timeout downloading large docs file
- **chunking/code_chunking.py, code_chunking_custom_tokenizer.py**: Missing tree_sitter_language_pack
- **chunking/csv_row_chunking.py**: Timeout embedding 1000 IMDB rows
- **readers/csv_reader.py**: Missing tmp/test.csv test file
- **readers/csv_reader_custom_encodings.py**: Wrong encoding (gb2312) for UTF-8 CSV
- **readers/csv_field_labeled_reader.py**: Timeout embedding 1000 IMDB rows
- **readers/firecrawl_reader.py**: API changed - scrape_url method no longer exists

## Notes

- Most SKIPs are due to missing cloud credentials, API keys, or external services
- PgVector running and all pgvector-dependent cookbooks pass
- No framework regressions detected - all failures are pre-existing cookbook issues
