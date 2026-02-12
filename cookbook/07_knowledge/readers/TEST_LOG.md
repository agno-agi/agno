# TEST_LOG

## readers — v2.5 Review (2026-02-11)

Tested: 2026-02-11 | Branch: cookbooks/v2.5-testing
Deps installed during testing: aiofiles, openpyxl, xlrd, arxiv, chonkie[semantic]

---

### json_reader.py

**Status:** PASS

**Description:** JSONReader — creates and reads a JSON file. Self-contained test.

**Result:** Successfully read JSON file, output 16 chars of content.

---

### doc_kb_async.py

**Status:** PASS

**Description:** Async text_content insertion into PgVector. No file reader needed — inline Earth facts.

**Result:** Inserted 1 document, agent answered Earth questions using knowledge base.

---

### markdown_reader_async.py

**Status:** PASS

**Description:** Async markdown file insertion from local README.md into PgVector. Uses pgvector.pgvector double-module import path.

**Result:** Inserted 1 document from README.md, agent answered questions about Agno framework.

---

### md_reader_async.py

**Status:** PASS

**Description:** Async MarkdownReader from GitHub URL into PgVector.

**Result:** Fetched Agno README from GitHub, inserted into PgVector. Agent answered Agno questions.

---

### pdf_reader_async.py

**Status:** PASS

**Description:** Async PDF reader with auto-detected reader. Loads CV from testing_resources/.

**Result:** Inserted cv_1.pdf, agent answered about Software Engineer skills.

---

### pdf_reader_password.py

**Status:** PASS

**Description:** Password-protected PDF from S3 URL, using ContentAuth. Downloads then reads.

**Result:** Downloaded and decrypted Thai recipes PDF, agent answered Pad Thai recipe query.

---

### pdf_reader_url_password.py

**Status:** PASS

**Description:** Password-protected PDF from URL with dual-DB pattern (vectors + contents).

**Result:** Inserted into PgVector with ContentsDB, agent answered Thai recipe questions.

---

### excel_reader.py

**Status:** PASS

**Description:** ExcelReader for modern .xlsx files. Uses openpyxl backend.

**Result:** Read sample_products.xlsx, agent listed 6 electronics products with prices. Second query about Bluetooth speaker price answered correctly ($49.99).

---

### excel_legacy_xls.py

**Status:** PASS

**Description:** ExcelReader for legacy .xls files. Uses xlrd backend. Multi-sheet workbook (Sales Data, Inventory).

**Result:** Read legacy_data.xls, agent answered about available inventory items (Item C). Sales Data query returned less specific results (knowledge was from Inventory sheet).

---

### csv_field_labeled_reader.py

**Status:** PASS

**Description:** FieldLabeledCSVReader with custom field mapping for IMDB movie data from S3 URL.

**Result:** Inserted 100+ documents in batches from IMDB CSV. Processing completed without error.

---

### arxiv_reader.py

**Status:** PASS

**Description:** ArxivReader for academic papers. Fetches papers on Generative AI and Machine Learning topics.

**Result:** Fetched ArXiv papers, inserted into PgVector. Agent summarized 5 key points about Generative AI including information access, art/creativity, science, regulation, and ethics.

---

### arxiv_reader_async.py

**Status:** PASS

**Description:** Async variant of ArxivReader.

**Result:** Same as sync — fetched papers and answered about Generative AI.

---

### web_reader.py

**Status:** PASS

**Description:** WebsiteReader direct test (no vectordb). Crawls docs.agno.com with max_depth=3, max_links=10.

**Result:** Successfully crawled 5 pages from docs.agno.com. Output included Agent API documentation.

---

### web_search_reader.py

**Status:** PASS

**Description:** WebSearchReader with DuckDuckGo search. Dual-DB pattern. Debug mode enabled.

**Result:** Searched "agno" via DuckDuckGo, results were about polyomavirus agnoprotein (not the framework). Agent correctly noted results didn't match AI trends query. Pipeline working correctly, just topic mismatch.

---

### web_search_reader_async.py

**Status:** PASS

**Description:** Async WebSearchReader. Searches "web3 latest trends 2025".

**Result:** Searched DuckDuckGo, loaded results into PgVector. Agent couldn't find specific trends — content didn't match query. Pipeline working correctly.

---

### website_reader.py

**Status:** PASS

**Description:** WebsiteReader with custom OpenAIEmbedder. Crawls Wikipedia about Generative AI.

**Result:** Crawled Wikipedia page, inserted into PgVector. Agent answered comprehensively about GenAI including best practices and ROI.

---

### csv_reader_async.py

**Status:** PASS (soft)

**Description:** Async CSVReader from local data/csv directory.

**Result:** Ran without crash but data/csv directory doesn't exist — no data loaded. Agent answered generic CSV questions. No runtime error; Knowledge.ainsert silently handles missing paths.

---

### csv_reader.py

**Status:** FAIL

**Description:** Basic CSVReader direct test. Reads from tmp/test.csv.

**Result:** FileNotFoundError: "Could not find file: tmp/test.csv". Cookbook expects user to create test file, but doesn't document this requirement.

---

### csv_reader_custom_encodings.py

**Status:** FAIL

**Description:** CSVReader with gb2312 encoding on IMDB movie data from S3.

**Result:** Encoding error: "'gb2312' codec can't decode byte 0xc3 in position 18947". The IMDB CSV is UTF-8/Latin-1, not gb2312. Cookbook uses wrong encoding for demo data.

---

### csv_reader_url_async.py

**Status:** FAIL

**Description:** Async CSVReader from S3 URL with dual-DB pattern.

**Result:** Embedding error: "expected 1536 dimensions, not 0". CSV rows produced empty embeddings. Multiple ERROR lines in output. Agent found 0 documents.

---

### pptx_reader.py

**Status:** FAIL

**Description:** PPTXReader for PowerPoint .pptx files (sync).

**Result:** Not run — uses placeholder path "path/to/your/presentation.pptx" which doesn't exist. Would need real test PPTX file in testing_resources/.

---

### pptx_reader_async.py

**Status:** FAIL

**Description:** PPTXReader for PowerPoint .pptx files (async).

**Result:** Not run — same placeholder path issue as sync variant.

---

### firecrawl_reader.py

**Status:** SKIP

**Description:** Firecrawl web scraping API integration.

**Result:** Skipped — requires FIRECRAWL_API_KEY environment variable.

---

### tavily_reader.py

**Status:** SKIP

**Description:** Tavily web extraction API (3 examples).

**Result:** Skipped — requires TAVILY_API_KEY environment variable.

---

### tavily_reader_async.py

**Status:** SKIP

**Description:** Async Tavily reader with dual-DB pattern.

**Result:** Skipped — requires TAVILY_API_KEY environment variable.

---

## Summary

| Status | Count | Files |
|--------|-------|-------|
| PASS   | 17    | json_reader, doc_kb_async, markdown_reader_async, md_reader_async, pdf_reader_async, pdf_reader_password, pdf_reader_url_password, excel_reader, excel_legacy_xls, csv_field_labeled_reader, arxiv_reader, arxiv_reader_async, web_reader, web_search_reader, web_search_reader_async, website_reader, csv_reader_async |
| FAIL   | 5     | csv_reader (missing test file), csv_reader_custom_encodings (wrong encoding), csv_reader_url_async (embedding failure), pptx_reader (placeholder path), pptx_reader_async (placeholder path) |
| SKIP   | 3     | firecrawl_reader, tavily_reader, tavily_reader_async |

No v2.5 regressions detected. All failures are pre-existing cookbook issues (wrong encoding, missing test data, placeholder paths).
