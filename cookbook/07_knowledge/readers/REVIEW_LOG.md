# REVIEW_LOG

## readers — v2.5 Review (2026-02-11)

Tested: 2026-02-11 | Branch: cookbooks/v2.5-testing
Deps installed during testing: aiofiles, openpyxl, xlrd, arxiv, chonkie[semantic]

---

## Framework Issues

[FRAMEWORK] agno/knowledge/knowledge.py — `Knowledge.search(search_type=...)` mutates `self.vector_db.search_type` permanently. If one query uses `search_type=SearchType.keyword`, all subsequent queries default to keyword. Applies to all reader cookbooks that use Knowledge.search().

[FRAMEWORK] agno/knowledge/reader/csv_reader.py — CSVReader with URL source produces empty embeddings for some CSV rows (0 dimensions instead of 1536). Seen in csv_reader_url_async.py with IMDB data. May be a chunking or content extraction issue where CSV rows produce empty text for the embedder.

[FRAMEWORK] agno/knowledge/reader/csv_reader.py:9-11 — `aiofiles` imported at module level blocks all sync CSV operations when aiofiles is not installed. Should defer import to async methods only.

[FRAMEWORK] agno/knowledge/reader/excel_reader.py — ExcelReader silently requires `openpyxl` (xlsx) and `xlrd` (xls) but these are not declared as agno dependencies. Users get ImportError at runtime.

[FRAMEWORK] agno/knowledge/reader/arxiv_reader.py — ArxivReader silently requires `arxiv` package. Not declared as agno dependency.

[FRAMEWORK] agno/knowledge/chunking/ — SemanticChunking import at module level in WebSearchReader requires `chonkie[semantic]`. Importing WebSearchReader fails even if you don't use semantic chunking.

---

## Cookbook Quality

[QUALITY] csv_reader.py — Reads from `tmp/test.csv` which doesn't exist. Cookbook expects user to create test file but doesn't document this requirement or create it programmatically.

[QUALITY] csv_reader_custom_encodings.py — Uses `gb2312` encoding on S3 IMDB CSV that is actually UTF-8/Latin-1. The encoding demo is broken because the data doesn't match the encoding.

[QUALITY] csv_reader_async.py — Reads from `data/csv` directory that doesn't exist. Silently produces no results (soft pass). Should either create test data or use a URL source.

[QUALITY] pptx_reader.py / pptx_reader_async.py — Both use placeholder path `path/to/your/presentation.pptx`. Should use a real test PPTX in testing_resources/ or an S3 URL.

[QUALITY] web_search_reader.py — Searches "agno" via DuckDuckGo but results are about polyomavirus agnoprotein, not the AI framework. Search query should be more specific.

[QUALITY] web_search_reader_async.py — Searches "web3 latest trends 2025" but content doesn't match agent's query about trends. Pipeline works but demo doesn't produce meaningful answers.

[QUALITY] doc_kb_async.py — Name suggests generic "document" knowledge base but actually uses inline text_content insertion. Could be clearer.

[QUALITY] excel_reader.py / excel_legacy_xls.py — Good quality. Use testing_resources/ with real test files. Well-structured with multiple query examples.

[QUALITY] pdf_reader_password.py / pdf_reader_url_password.py — Good quality. Demonstrate ContentAuth pattern clearly. S3 URL sources work reliably.

[QUALITY] All reader cookbooks — Hardcoded `postgresql+psycopg://ai:ai@localhost:5532/ai` connection strings. Should use environment variable.

---

## Fixes Applied

None — all failures are pre-existing cookbook issues (wrong encoding, missing test data, placeholder paths). No v2.5 regressions detected.
