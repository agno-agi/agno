"""
agno.tools.finance — one finance toolkit, swappable data providers.

```python
from agno.agent import Agent
from agno.tools.finance import FinanceTools
from agno.tools.finance.providers import FinancialDatasets

agent = Agent(model="openai:gpt-5.6", tools=[FinanceTools()])                       # Yahoo Finance, no key
agent = Agent(model="openai:gpt-5.6", tools=[FinanceTools(provider=FinancialDatasets())])
agent.print_response("Give me a market brief on NVIDIA", stream=True)
```

Providers live in `agno.tools.finance.providers` (`YFinance`, `FinancialDatasets`)
and are re-exported here for one-line imports. Bring your own by subclassing
`FinanceProvider`.
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
from agno.tools.finance.providers import FinancialDatasets, YFinance
from agno.tools.finance.toolkit import FinanceTools

__all__ = [
    "ALL_CAPABILITIES",
    "AnalystRecommendations",
    "CompanyProfile",
    "EarningsReport",
    "Filing",
    "FinanceProvider",
    "FinanceProviderError",
    "FinanceTools",
    "FinancialDatasets",
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
    "YFinance",
    "register_provider",
    "registered_providers",
]
