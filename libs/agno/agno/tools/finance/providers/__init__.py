"""
Data providers for `FinanceTools`.

```python
from agno.tools.finance import FinanceTools
from agno.tools.finance.providers import FinancialDatasets, YFinance

FinanceTools(provider=YFinance())            # default: no API key
FinanceTools(provider=FinancialDatasets())   # FINANCIAL_DATASETS_API_KEY
```

Bring your own by subclassing `agno.tools.finance.FinanceProvider`.
"""

from agno.tools.finance.providers.financial_datasets import FinancialDatasets
from agno.tools.finance.providers.yfinance import YFinance

__all__ = ["FinancialDatasets", "YFinance"]
