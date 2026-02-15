# Test Log — readers

Tested: 2026-02-12 | Branch: cookbook/v25-merge-fixes

| File | Status | Notes |
|------|--------|-------|
| arxiv_reader.py | PASS | Fetched ArXiv papers on Generative AI, agent summarized key points |
| arxiv_reader_async.py | PASS | Async variant, fetched papers and answered about Generative AI |
| csv_field_labeled_reader.py | FAIL | Timeout: embedding 1000 IMDB rows exceeds 120s limit |
| csv_reader.py | FAIL | FileNotFoundError: tmp/test.csv missing (cookbook expects user-created file) |
| csv_reader_async.py | PASS | Async CSV from local path, ran without crash |
| csv_reader_custom_encodings.py | FAIL | Encoding error: gb2312 codec can't decode IMDB CSV (wrong encoding for data) |
| csv_reader_url_async.py | PASS | Async CSV from S3 URL, ran but agent couldn't find specific genre data |
| doc_kb_async.py | PASS | Async text_content insertion, agent answered Earth questions |
| excel_legacy_xls.py | PASS | Legacy .xls reader, answered inventory questions |
| excel_reader.py | PASS | Modern .xlsx reader, listed products and prices correctly |
| firecrawl_reader.py | FAIL | AttributeError: 'Firecrawl' object has no attribute 'scrape_url' |
| json_reader.py | PASS | JSON reader, read file successfully |
| markdown_reader_async.py | PASS | Async markdown from local README, agent answered about Agno |
| md_reader_async.py | PASS | Async markdown from GitHub URL, agent answered about Agno |
| pdf_reader_async.py | PASS | Async PDF reader, agent answered about SE skills |
| pdf_reader_password.py | PASS | Password-protected PDF from S3, Pad Thai recipe query worked |
| pdf_reader_url_password.py | PASS | Password-protected PDF with dual-DB pattern |
| pptx_reader.py | PASS | PPTX reader ran but no documents found (no test pptx file in KB) |
| pptx_reader_async.py | PASS | Async PPTX reader ran but no documents found |
| tavily_reader.py | SKIP | Missing: TAVILY_API_KEY |
| tavily_reader_async.py | PASS | Tavily extract API worked, agent explained the API |
| web_reader.py | PASS | Crawled docs.agno.com, read Agent API docs |
| web_search_reader.py | PASS | DuckDuckGo search, loaded results into PgVector |
| web_search_reader_async.py | PASS | Async DuckDuckGo search, loaded results |
| website_reader.py | PASS | Crawled Wikipedia GenAI page, agent answered comprehensively |

## Summary

| Status | Count |
|--------|-------|
| PASS   | 20    |
| FAIL   | 4     |
| SKIP   | 1     |

FAIL: csv_field_labeled_reader.py (timeout), csv_reader.py (missing test file), csv_reader_custom_encodings.py (wrong encoding), firecrawl_reader.py (API method changed)
SKIP: tavily_reader.py (API key missing)
