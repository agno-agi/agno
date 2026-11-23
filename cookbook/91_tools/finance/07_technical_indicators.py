"""
Technical Indicators with TA-Lib
================================
FinanceTools returns price bars and computes nothing from them. This example
adds two plain function tools that do, next to `FinanceTools()`:
`get_momentum_indicators` (RSI and MACD) and `scan_candlestick_patterns`,
both computed with TA-Lib.

Each tool fetches its own daily bars by calling the default provider directly
(see "Using a provider directly" in the README), so the model never copies a
price series into a tool call, and returns a few rows instead of the series.

The two tools run without a model key: `__main__` prints their output before
the agent call. Layout follows 06_custom_provider.py.

Prompts to try:
- "Where do RSI and MACD stand on NVDA, and what do they say together?"
- "Any candlestick patterns on AMD in the last two weeks?"

Run: pip install yfinance TA-Lib (prebuilt TA-Lib wheels need Python 3.10 or later)
"""

import json
from typing import Any, Dict, List, Tuple

import numpy as np
from agno.agent import Agent
from agno.tools.finance import FinanceProviderError, FinanceTools
from agno.tools.finance.providers import YFinance
from talib import abstract

# ---------------------------------------------------------------------------
# Indicator tools
# ---------------------------------------------------------------------------
provider = YFinance()
ROWS = 5  # indicator rows returned to the model
SCAN_BARS = 10  # most recent bars scanned for candlestick patterns
# For these three the sign is the direction: positive is bullish, negative bearish.
PATTERNS = ("CDLENGULFING", "CDLHAMMER", "CDLSHOOTINGSTAR")


def _daily_bars(
    symbol: str, period: str, need: int
) -> Tuple[List[str], Dict[str, Any]]:
    if not symbol:
        raise FinanceProviderError("symbol is required")
    history = provider.get_price_history(symbol, period=period, interval="1d")
    # Bar fields are optional, and a NaN inside the input makes later outputs undefined.
    bars = [b for b in history.bars if None not in (b.open, b.high, b.low, b.close)]
    bars.sort(key=lambda b: b.date)  # oldest first
    if len(bars) < need:
        raise FinanceProviderError(
            f"{len(bars)} bars, need {need}: use a longer period"
        )
    fields = ("open", "high", "low", "close")
    ohlc = {f: np.array([getattr(b, f) for b in bars], dtype=float) for f in fields}
    return [b.date for b in bars], ohlc


def _reply(symbol: str, **fields: Any) -> str:
    return json.dumps({"symbol": symbol, **fields, "provider": provider.id})


def _round(value: float) -> float:
    # As FinanceTools rounds: 4 decimals, 4 significant digits below 0.01.
    return round(value, 4) if abs(value) >= 0.01 else float(f"{value:.4g}")


def get_momentum_indicators(symbol: str, period: str = "1y") -> str:
    """RSI(14) and MACD(12, 26, 9) on daily closes for the last 5 daily bars, computed with TA-Lib.

    Closes are split-adjusted but not dividend-adjusted: a drop on an ex-dividend date is in
    the values and is not a market move. The last bar may be a session still in progress.

    Args:
        symbol (str): Ticker symbol, e.g. NVDA.
        period (str): History to compute over: 6mo, 1y, 2y or 5y. Only the last 5 rows are returned.
    """
    rsi, macd = abstract.Function("RSI"), abstract.Function("MACD")
    # A function's first `lookback` outputs are not values, so none may be returned. Both
    # are EMA-based and keep settling after that, hence a year of bars by default.
    need = max(rsi.lookback, macd.lookback) + ROWS
    try:
        dates, ohlc = _daily_bars(symbol, period, need)
    except FinanceProviderError as e:
        return _reply(symbol, error=str(e))
    out = {"close": ohlc["close"], "rsi": rsi(ohlc)}
    out["macd"], out["macd_signal"], out["macd_hist"] = macd(ohlc)
    results = [
        {"date": dates[i], **{k: _round(float(v[i])) for k, v in out.items()}}
        for i in range(len(dates) - ROWS, len(dates))
    ]
    return _reply(symbol, period=period, interval="1d", results=results)


def scan_candlestick_patterns(symbol: str, period: str = "3mo") -> str:
    """Candlestick patterns found on the last 10 daily bars, detected with TA-Lib.

    Scans engulfing, hammer and shooting star. Each result is a TA-Lib function name and its
    raw value on the bar that completes the pattern: non-zero means found, positive is
    bullish, negative bearish. No function checks the prior trend, and the last bar may be
    a session still in progress. An empty `results` means none of the three was found.

    Args:
        symbol (str): Ticker symbol, e.g. NVDA.
        period (str): History to fetch: 3mo, 6mo or 1y. Only the last 10 bars are scanned.
    """
    functions = [abstract.Function(name) for name in PATTERNS]
    try:
        need = max(f.lookback for f in functions) + SCAN_BARS
        dates, ohlc = _daily_bars(symbol, period, need)
    except FinanceProviderError as e:
        return _reply(symbol, error=str(e))
    results = []
    for name, function in zip(PATTERNS, functions):
        values = function(ohlc)
        for i in range(len(dates) - SCAN_BARS, len(dates)):
            # The size of a hit differs between functions: test for non-zero only.
            if values[i] != 0:
                hit = {"date": dates[i], "pattern": name, "value": int(values[i])}
                results.append(hit)
    results.sort(key=lambda hit: hit["date"])
    return _reply(symbol, scanned_from=dates[-SCAN_BARS], results=results)


# ---------------------------------------------------------------------------
# Create the Agent
# ---------------------------------------------------------------------------
agent = Agent(
    name="Technical Analyst",
    model="openai:gpt-5.6",
    tools=[FinanceTools(), get_momentum_indicators, scan_candlestick_patterns],
    instructions="Quote indicator and pattern values from the tools. Never work one out from raw bars.",
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run the Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print(get_momentum_indicators("NVDA"))
    print(scan_candlestick_patterns("NVDA"))
    agent.print_response(
        "Where do RSI and MACD stand on NVDA, and did any candlestick pattern complete in the last two weeks?",
        stream=True,
    )
