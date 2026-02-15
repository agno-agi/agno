# TEST_LOG

## v2.5 Testing — 2026-02-11

### basic.py
**Status:** PASS
**Description:** Basic agent with Claude (sync, sync+stream, async, async+stream). All 4 variants working.

---

### basic_with_timeout.py
**Status:** PASS
**Description:** Agent with 1s timeout. Correctly demonstrates timeout behavior with Anthropic API overloaded error.

---

### betas.py
**Status:** PASS
**Description:** Lists available Anthropic beta features and runs agent with beta enabled.

---

### code_execution.py
**Status:** PASS
**Description:** Uses code-execution beta to calculate mean and standard deviation.

---

### context_management.py
**Status:** PASS
**Description:** Context management beta for automatic tool result clearing. Reduces token usage.

---

### csv_input.py
**Status:** PASS
**Description:** CSV file analysis using File media type. Downloads IMDB dataset and analyzes top movies.

---

### db.py
**Status:** PASS
**Description:** Agent with PostgresDb for session history. Multi-turn conversation about Canada.

---

### financial_analyst_thinking.py
**Status:** PASS
**Description:** Interleaved thinking beta with calculator and YFinance tools for portfolio analysis.

---

### image_input_bytes.py
**Status:** FAIL
**Description:** Downloads image then passes as bytes. `download_image` fails silently, causing FileNotFoundError on `sample.jpg`.
**Result:** `FileNotFoundError: No such file or directory: '.../sample.jpg'`

---

### image_input_file_upload.py
**Status:** FAIL
**Description:** Uploads image to Anthropic Files API then uses as input. `Image(content=uploaded_file)` fails because `uploaded_file` is `FileMetadata`, not `bytes`.
**Result:** `pydantic ValidationError: Input should be a valid bytes`

---

### image_input_local_file.py
**Status:** PASS
**Description:** Image input from local file path. Downloads image and passes via filepath.

---

### image_input_url.py
**Status:** PASS
**Description:** Image input from URL with web search tools. Golden Gate Bridge analysis.

---

### knowledge.py
**Status:** PASS
**Description:** Knowledge base with AzureOpenAIEmbedder and PgVector. PDF embedding pipeline works (slow due to embedding).

---

### mcp_connector.py
**Status:** PASS
**Description:** MCP server connector beta with DeepWiki MCP server.

---

### memory.py
**Status:** PASS
**Description:** Agent memory with PostgresDb. Multi-turn conversation storing personal info.

---

### pdf_input_bytes.py
**Status:** FAIL
**Description:** PDF as bytes input. `agent.get_last_run_output()` returns None after `print_response()`, causing AttributeError on `.citations`.
**Result:** `AttributeError: 'NoneType' object has no attribute 'citations'`

---

### pdf_input_file_upload.py
**Status:** PASS
**Description:** PDF upload to Anthropic Files API. Works correctly with files beta.

---

### pdf_input_local.py
**Status:** FAIL
**Description:** Same issue as pdf_input_bytes.py. `agent.get_last_run_output()` returns None.
**Result:** `AttributeError: 'NoneType' object has no attribute 'citations'`

---

### pdf_input_url.py
**Status:** PASS
**Description:** PDF input from URL. Thai recipes summarization works correctly.

---

### prompt_caching.py
**Status:** PASS
**Description:** System prompt caching. Downloads large system prompt, demonstrates cache write then cache read tokens.

---

### prompt_caching_extended.py
**Status:** PASS
**Description:** Extended 1-hour cache TTL beta. Downloads system prompt and demonstrates extended caching.

---

### retry.py
**Status:** PASS
**Description:** Retry demonstration with wrong model ID. Shows 3 retries with exponential backoff, then fails as expected.

---

### structured_output.py
**Status:** PASS
**Description:** Pydantic MovieScript schema output with Claude Opus. Sync and sync+stream variants.

---

### structured_output_strict_tools.py
**Status:** PASS
**Description:** Strict tool parameter validation with Function class. Weather tool with structured output.

---

### thinking.py
**Status:** PASS
**Description:** Extended thinking with Claude 3.7 Sonnet. Shows thinking content in response.

---

### tool_use.py
**Status:** PASS
**Description:** WebSearchTools with Claude. Sync, sync+stream, async+stream variants working.

---

### web_fetch.py
**Status:** PASS
**Description:** Web fetch beta tool for reading web pages. Fetches Wikipedia article.

---

### web_search.py
**Status:** PASS
**Description:** Anthropic native web search tool with metrics. Shows web search request count.

---

## Summary
- **PASS:** 24/28 (86%)
- **FAIL:** 4/28 (14%)
- **Failures:**
  - image_input_bytes.py: download_image fails silently
  - image_input_file_upload.py: Image(content=FileMetadata) type mismatch
  - pdf_input_bytes.py: get_last_run_output() returns None
  - pdf_input_local.py: get_last_run_output() returns None
