"""
agno.tools.finance — one finance toolkit, swappable data providers.

```python
from agno.agent import Agent
from agno.tools.finance import FinanceTools

agent = Agent(model="openai:gpt-5.6", tools=[FinanceTools()])
agent.print_response("Give me a market brief on NVIDIA", stream=True)
```

Providers: `YFinanceProvider` (default, no key), `FinancialDatasetsProvider`
(financialdatasets.ai, `FINANCIAL_DATASETS_API_KEY`). Bring your own by
subclassing `FinanceProvider`.
"""

from agno.tools.finance.base import (
    ALL_CAPABILITIES,
    AnalystRecommendations,
    CompanyProfile,
    EarningsReport,
    Filing,
    FinanceProvider,
    FinanceProviderError,
    FinancialStatement,
    InsiderTrade,
    KeyMetrics,
    NewsItem,
    NotSupportedError,
    PriceBar,
    PriceHistory,
    ProviderStatus,
    Quote,
    SymbolMatch,
    register_provider,
    registered_providers,
)
from agno.tools.finance.financial_datasets import FinancialDatasetsProvider
from agno.tools.finance.toolkit import FinanceTools
from agno.tools.finance.yfinance import YFinanceProvider

__all__ = [
    "ALL_CAPABILITIES",
    "AnalystRecommendations",
    "CompanyProfile",
    "EarningsReport",
    "Filing",
    "FinanceProvider",
    "FinanceProviderError",
    "FinanceTools",
    "FinancialDatasetsProvider",
    "FinancialStatement",
    "InsiderTrade",
    "KeyMetrics",
    "NewsItem",
    "NotSupportedError",
    "PriceBar",
    "PriceHistory",
    "ProviderStatus",
    "Quote",
    "SymbolMatch",
    "YFinanceProvider",
    "register_provider",
    "registered_providers",
]
