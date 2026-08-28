# Finance Tools - Test Log

## 2026-08-18

Environment: `.venvs/demo` (yfinance 1.6.0), `openai:gpt-5.6`, no `FINANCIAL_DATASETS_API_KEY` available.

### 01_market_brief.py

**Status:** PASS

**Description:** `FinanceTools()` (yfinance default, 7 tools) on a gpt-5.6 agent, prompt "Give me a market brief on NVIDIA".

**Result:** One parallel round of six tool calls (`get_quote`, `get_price_history`, `get_company_profile`, `get_key_metrics`, `get_news`, `get_analyst_recommendations`; `search_symbols` skipped because the ticker was known). Brief led with price/day change, then valuation table, Wall Street view (61 analysts, mean target 302.83), risks, and closed with "NVDA, USD, Nasdaq; Yahoo Finance via yfinance ... as of August 18, 2026, 11:19 UTC" - the toolkit instructions were followed. No invented numbers.

---

### 02_financial_datasets.py

**Status:** PASS (live)

**Description:** `FinanceTools(provider=FinancialDatasets(), all=True)`; 9 tools registered (no `search_symbols`, no `get_analyst_recommendations`). Prompt asks for a market brief on NVIDIA including last quarter's revenue and net margin.

**Result:** Without a key, every tool returned `{"error": "FINANCIAL_DATASETS_API_KEY not configured", ...}` and the agent reported N/A for every figure plus "API key not configured" - no hallucinated data. With an invalid key the real API returned 401, rendered as `HTTP 401 (invalid API key): Invalid API key`. With a real key (fresh account, no credits) every endpoint - including NVDA - returned `HTTP 402 (payment required: no credits or plan does not cover this request): Insufficient credits`, and a bogus ticker returned `HTTP 400 (bad request): Invalid ticker`; both rendered cleanly through the envelope, sync and async, in 4.8 s for the whole sweep. That confirms auth header, every endpoint path and every query-param set are accepted by the server; response normalization on 200 payloads is covered by 28 mocked unit tests built from the 2026-08-18 OpenAPI spec (`libs/agno/tests/unit/tools/test_finance_financial_datasets_provider.py`). Once credits were added to the account, a raw sweep of all 9 tools returned real normalized payloads sync and async in 15 s (quote 220.64 USD as of 2026-08-18T11:38:07Z; 5d/1d bars; company facts with CIK; metrics snapshot with market cap 5.44T, P/E 34.4; quarterly income statement for 2027-Q1 with revenue 81.6B; annual balance sheet; ttm cash flow; news with URLs; insider grants; earnings tied to 8-K/10-Q filing URLs; 10-Q filings with accession numbers). The agent run then produced the brief with those figures and closed with "Data provider: Financial Datasets (financialdatasets.ai)". Observation: `/earnings` returns one record per source filing (8-K and 10-Q for the same quarter), so the same report period can appear twice with different filing URLs.

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

**Result:** `pytest libs/agno/tests/unit/tools/test_finance*.py` - 116 passed, 1 skipped in `.venv` (yfinance provider tests skip without yfinance); 149 passed in `.venvs/demo`. Includes every tool sync + async through the toolkit, financialdatasets pagination and sync/async request parity, and yfinance normalizers against 1.6.0-shaped objects.
