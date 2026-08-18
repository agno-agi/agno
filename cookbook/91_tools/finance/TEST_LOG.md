# Finance Tools - Test Log

## 2026-08-18

Environment: `.venvs/demo` (yfinance 1.6.0), `openai:gpt-5.6`, no `FINANCIAL_DATASETS_API_KEY` available.

### 01_market_brief.py

**Status:** PASS

**Description:** `FinanceTools()` (yfinance default, 7 tools) on a gpt-5.6 agent, prompt "Give me a market brief on NVIDIA".

**Result:** One parallel round of six tool calls (`get_quote`, `get_price_history`, `get_company_profile`, `get_key_metrics`, `get_news`, `get_analyst_recommendations`; `search_symbols` skipped because the ticker was known). Brief led with price/day change, then valuation table, Wall Street view (61 analysts, mean target 302.83), risks, and closed with "NVDA, USD, Nasdaq; Yahoo Finance via yfinance ... as of August 18, 2026, 11:19 UTC" - the toolkit instructions were followed. No invented numbers.

---

### 02_financial_datasets.py

**Status:** PASS (no-key path) / NOT RUN (live)

**Description:** `FinanceTools(provider="financial_datasets", all=True)`; 9 tools registered (no `search_symbols`, no `get_analyst_recommendations`).

**Result:** Without a key, every tool returned `{"error": "FINANCIAL_DATASETS_API_KEY not configured", ...}` and the agent reported N/A for every figure plus "API key not configured" - no hallucinated data. Against the real API with an invalid key the provider rendered `HTTP 401 (invalid API key): Invalid API key`. Request/response normalization is covered by 27 mocked unit tests built from the 2026-08-18 OpenAPI spec (`libs/agno/tests/unit/tools/test_finance_financial_datasets_provider.py`). A live pass with a real key is still owed.

---

### 03_swap_provider.py

**Status:** PASS (yfinance branch)

**Description:** Builds one agent per configured provider and runs "What is Apple's current price, P/E and market cap?" through each. Only yfinance was configured in this environment.

**Result:** `get_quote` + `get_key_metrics`; answer stated price 305.59 USD, trailing P/E 35.09, market cap 4.46T, as-of and provider. financialdatasets branch not exercised (no key).

---

### 04_analyst_mode.py

**Status:** PASS

**Description:** `FinanceTools(all=True)` (11 tools) with an equity-analyst persona; prompt asks for 4 quarters of revenue and net margin, insider activity, next earnings date, most recent 8-K.

**Result:** Agent called `get_financials(statement=income, period=quarterly)`, `get_insider_trades`, `get_earnings`, `get_sec_filings(form_type=8-K)`. Computed net margins from line items, tabulated insider sales (Mark Stevens 2.1M shares) vs gifts/grants, reported next earnings 2026-08-26 16:00 ET with 2.08 EPS estimate, and marked 8-K item numbers as N/A rather than inferring them.

---

### 05_async.py

**Status:** PASS

**Description:** One agent, `asyncio.gather` over `agent.arun()` for NVDA, AMD, AVGO; async tool variants used automatically.

**Result:** Three concise three-bullet takes with prices, valuation and a headline each, all stamped as of 11:22 UTC. Sync provider ran in worker threads without issue.

---

### 06_custom_provider.py

**Status:** PASS

**Description:** `InternalPricesProvider(FinanceProvider)` serving `get_quote` + `search_symbols` from a dict, registered under id "internal", selected with `FinanceTools(provider="internal")`.

**Result:** Toolkit registered exactly two tools; agent called `search_symbols` for both names, then `get_quote(ACME)` / `get_quote(GLOBX)` and answered with the internal prices, as-of and provider name.

---

### Unit tests

**Status:** PASS

**Result:** `pytest libs/agno/tests/unit/tools/test_finance*.py` - 61 passed, 1 skipped in `.venv` (yfinance provider tests skip without yfinance); 84 passed in `.venvs/demo`.
