# Finance Tools

One finance toolkit, swappable data providers. `FinanceTools` gives an agent a fixed set of market-data tools that return the same JSON shape no matter which provider is behind them. Change the provider with one argument; the agent code never changes.

```python
from agno.agent import Agent
from agno.tools.finance import FinanceTools

agent = Agent(
    name="Finance Agent",
    model="openai:gpt-5.6",
    tools=[FinanceTools()],
    instructions="Lead with the answer, then show the evidence.",
)

agent.print_response("Give me a market brief on NVIDIA", stream=True)
```

Swap the data provider with one argument:

```python
from agno.tools.finance.providers import FinancialDatasets

agent = Agent(model="openai:gpt-5.6", tools=[FinanceTools(provider=FinancialDatasets())])
```

## Overview

Tools (frozen names; every tool has a sync and an async variant):

| Tool | What it returns | Default |
|------|-----------------|---------|
| `search_symbols(query, limit)` | company name -> ticker matches | on |
| `get_quote(symbol)` | price, day change, OHLC, volume, market cap, 52-week range, `as_of` | on |
| `get_price_history(symbol, period, interval)` | OHLCV bars (`period` 1d..max, `interval` 1d/1wk/1mo) | on |
| `get_company_profile(symbol)` | name, description, sector, industry, exchange, location, employees | on |
| `get_key_metrics(symbol)` | market cap, P/E, PEG, P/B, P/S, EV/EBITDA, EPS, margins, growth, leverage | on |
| `get_news(symbol, limit)` | recent headlines with source, url, published_at | on |
| `get_analyst_recommendations(symbol)` | consensus, rating counts, price targets | on |
| `get_financials(symbol, statement, period, limit)` | income / balance_sheet / cash_flow by annual / quarterly / ttm | `all=True` or `financials=True` |
| `get_insider_trades(symbol, limit)` | insider buys, sells, grants | `all=True` or `insider_trades=True` |
| `get_earnings(symbol, limit)` | reported vs estimated EPS by period, upcoming dates | `all=True` or `earnings=True` |
| `get_sec_filings(symbol, form_type, limit)` | recent filings with links | `all=True` or `sec_filings=True` |

Every payload carries `provider` (which data source answered) and, where available, `as_of`. Errors come back as `{"error": "...", "symbol": "...", "provider": "..."}` so the model can say "N/A" instead of guessing.

## Providers

| Provider | `provider=` | Key | Serves | Notes |
|----------|-------------|-----|--------|-------|
| Yahoo Finance (`yfinance`) | `YFinance()` (default) or `"yfinance"` | none | all 11 tools | `pip install yfinance`. Unofficial, rate-limited under load, personal-use terms. |
| financialdatasets.ai | `FinancialDatasets()` or `"financial_datasets"` | `FINANCIAL_DATASETS_API_KEY` | 9 tools (no `search_symbols`, no `get_analyst_recommendations`) | Structured, real-time, commercial use on all plans. Requests cost credits (see financialdatasets.ai/pricing). No extra dependency. |
| Your own | `FinanceProvider` subclass | - | whatever it declares | See `06_custom_provider.py`. |

Providers live in `agno.tools.finance.providers` and are re-exported from `agno.tools.finance`. Pass an instance (recommended: constructor kwargs like `api_key`, `timeout`, `session` are explicit) or a registered id string (handy for env/config-driven setups). The toolkit registers only the tools the selected provider declares, so the model never sees a tool it cannot use.

## Examples

| File | Description |
|------|-------------|
| `01_market_brief.py` | The simplest finance agent: `FinanceTools()`, no key, "market brief on NVIDIA" |
| `02_financial_datasets.py` | Same agent on financialdatasets.ai (`provider="financial_datasets"`, `all=True`) |
| `03_swap_provider.py` | Same agent, one per configured provider, same prompt - compare answers |
| `04_analyst_mode.py` | `all=True`: statements, insider trades, earnings, filings for a deep dive |
| `05_async.py` | `agent.arun()` fanned out over three tickers; async tool variants used automatically |
| `06_custom_provider.py` | Bring your own provider (an internal price table) and register it by id |

## Configuration

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `provider` | `FinanceProvider \| str \| None` | `None` | Provider instance (e.g. `FinancialDatasets()`), registered id (`"financial_datasets"`), or None (`YFinance()` if `yfinance` is installed, else `FinancialDatasets()` if its key is set) |
| `search_symbols`, `quote`, `price_history`, `company_profile`, `key_metrics`, `news`, `analyst_recommendations` | `bool` | `True` | Market-brief tools |
| `financials`, `insider_trades`, `earnings`, `sec_filings` | `bool` | `False` | Analyst tools (larger payloads) |
| `all` | `bool` | `False` | Register every tool the provider supports |
| `instructions` / `add_instructions` | `str` / `bool` | generated / `True` | Toolkit instructions listing the registered tools and data-handling rules |
| `timeout` | `float` | provider default | Forwarded when the provider is built from an id / None |
| `include_tools`, `exclude_tools`, `cache_results`, ... | | | Standard `Toolkit` options |

## Using a provider directly

Providers are usable without an agent and return typed dataclasses:

```python
from agno.tools.finance.providers import YFinance

quote = YFinance().get_quote("NVDA")
print(quote.price, quote.currency, quote.as_of)
```

## Running

```bash
# Ensure the demo environment is set up
./scripts/demo_setup.sh

# Default provider (yfinance) - no key needed
.venvs/demo/bin/python cookbook/91_tools/finance/01_market_brief.py

# financialdatasets.ai
export FINANCIAL_DATASETS_API_KEY=...
.venvs/demo/bin/python cookbook/91_tools/finance/02_financial_datasets.py
```
