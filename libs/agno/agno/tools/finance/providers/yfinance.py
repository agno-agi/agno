"""
YFinance — Yahoo Finance data provider via the `yfinance` package.

The default provider for `FinanceTools`: no API key, covers every capability.
Caveats: unofficial (scrapes Yahoo), rate-limited under load, and Yahoo's
terms describe the data as for personal use. Swap to another provider with
`FinanceTools(provider=...)` when that matters.

Requires `pip install yfinance`.
"""

import math
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from agno.tools.finance.base import (
    ALL_CAPABILITIES,
    INTERVALS,
    PERIODS,
    STATEMENT_PERIODS,
    STATEMENTS,
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
    PriceBar,
    PriceHistory,
    ProviderStatus,
    Quote,
    SymbolMatch,
)
from agno.utils.log import log_debug

_INSTALL_HINT = "`yfinance` not installed. Please install using `pip install yfinance`."


def _yf() -> Any:
    try:
        import yfinance
    except ImportError as e:
        raise ImportError(_INSTALL_HINT) from e
    return yfinance


class YFinance(FinanceProvider):
    """Yahoo Finance data through `yfinance`.

    Args:
        session: Optional requests-compatible session passed to `yfinance.Ticker`
            (e.g. a `curl_cffi` session with a browser impersonation profile).
        timeout: Per-request timeout in seconds for history and symbol search.
    """

    id = "yfinance"
    name = "Yahoo Finance (yfinance)"
    capabilities = ALL_CAPABILITIES

    def __init__(self, session: Optional[Any] = None, timeout: Optional[float] = None) -> None:
        self.session = session
        self.timeout = timeout

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    def status(self) -> ProviderStatus:
        try:
            yf = _yf()
        except ImportError as e:
            return ProviderStatus(ok=False, detail=str(e))
        version = getattr(yf, "__version__", "unknown")
        return ProviderStatus(ok=True, detail=f"yfinance {version} (unofficial Yahoo Finance API, no key)")

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _ticker(self, symbol: str) -> Any:
        return _yf().Ticker(symbol, session=self.session)

    @staticmethod
    def _info(ticker: Any, symbol: str) -> Dict[str, Any]:
        info = ticker.info
        if not isinstance(info, dict) or len(info) <= 1:
            # yfinance returns {"trailingPegRatio": None} for unknown symbols
            raise FinanceProviderError(f"No data found for symbol {symbol}; check the ticker")
        return info

    # ------------------------------------------------------------------
    # Capabilities
    # ------------------------------------------------------------------

    def search_symbols(self, query: str, limit: int = 5) -> List[SymbolMatch]:
        kwargs: Dict[str, Any] = {"max_results": limit, "news_count": 0}
        if self.session is not None:
            kwargs["session"] = self.session
        if self.timeout is not None:
            kwargs["timeout"] = self.timeout
        try:
            search = _yf().Search(query, **kwargs)
            quotes = list(getattr(search, "quotes", None) or [])
        except Exception as e:
            raise FinanceProviderError(f"Symbol search failed for {query!r}: {e}") from e
        matches: List[SymbolMatch] = []
        for q in quotes[:limit]:
            if not isinstance(q, dict) or not q.get("symbol"):
                continue
            matches.append(
                SymbolMatch(
                    symbol=str(q["symbol"]),
                    name=q.get("longname") or q.get("shortname"),
                    exchange=q.get("exchDisp") or q.get("exchange"),
                    type=q.get("quoteType"),
                )
            )
        return matches

    def get_quote(self, symbol: str) -> Quote:
        ticker = self._ticker(symbol)
        try:
            fast = ticker.fast_info
            price = _num(_get(fast, "lastPrice"))
        except Exception as e:
            raise FinanceProviderError(f"No quote data for symbol {symbol}: {e}") from e
        if price is None:
            raise FinanceProviderError(f"No quote data for symbol {symbol}; check the ticker")
        # regularMarketPreviousClose is the prior regular-session close (what
        # Yahoo shows); previousClose is the last extended-hours print of the
        # previous calendar day. Prefer the regular one, fall back to the other.
        previous_close = _num(_get(fast, "regularMarketPreviousClose"))
        if previous_close is None:
            previous_close = _num(_get(fast, "previousClose"))
        change: Optional[float] = None
        change_percent: Optional[float] = None
        if previous_close is not None:
            change = price - previous_close
            if previous_close != 0:
                change_percent = change / previous_close * 100
        return Quote(
            symbol=symbol,
            price=price,
            currency=_get(fast, "currency"),
            change=change,
            change_percent=change_percent,
            open=_num(_get(fast, "open")),
            high=_num(_get(fast, "dayHigh")),
            low=_num(_get(fast, "dayLow")),
            previous_close=previous_close,
            volume=_num(_get(fast, "lastVolume")),
            market_cap=_num(_get(fast, "marketCap")),
            fifty_two_week_high=_num(_get(fast, "yearHigh")),
            fifty_two_week_low=_num(_get(fast, "yearLow")),
            exchange=_get(fast, "exchange"),
            as_of=_now(),
        )

    def get_price_history(self, symbol: str, period: str = "1mo", interval: str = "1d") -> PriceHistory:
        if period not in PERIODS:
            raise FinanceProviderError(f"period must be one of {', '.join(PERIODS)}")
        if interval not in INTERVALS:
            raise FinanceProviderError(f"interval must be one of {', '.join(INTERVALS)}")
        ticker = self._ticker(symbol)
        # auto_adjust=False: Yahoo's raw OHLC is already split-adjusted, and
        # auto_adjust=True multiplies O/H/L/C by Adj Close/Close, which is NaN
        # for the latest session while Yahoo's adjclose lags -> a NaN bar.
        kwargs: Dict[str, Any] = {"period": period, "interval": interval, "auto_adjust": False}
        if self.timeout is not None:
            kwargs["timeout"] = self.timeout
        try:
            frame = ticker.history(**kwargs)
        except Exception as e:
            raise FinanceProviderError(f"Price history failed for {symbol}: {e}") from e
        if frame is None or getattr(frame, "empty", True):
            raise FinanceProviderError(f"No price history for symbol {symbol} (period={period}, interval={interval})")

        bars: List[PriceBar] = []
        for row in frame.itertuples():
            close = _num(getattr(row, "Close", None))
            if close is None:
                # Volume-only rows (Yahoo has not published the session's close yet) are not bars.
                continue
            bars.append(
                PriceBar(
                    date=_date(row.Index) or str(row.Index),
                    open=_num(getattr(row, "Open", None)),
                    high=_num(getattr(row, "High", None)),
                    low=_num(getattr(row, "Low", None)),
                    close=close,
                    volume=_num(getattr(row, "Volume", None)),
                )
            )
        if not bars:
            raise FinanceProviderError(f"No price history for symbol {symbol} (period={period}, interval={interval})")
        currency: Optional[str] = None
        try:
            currency = _get(ticker.fast_info, "currency")
        except Exception:
            log_debug(f"yfinance: could not read currency for {symbol}")
        return PriceHistory(symbol=symbol, period=period, interval=interval, currency=currency, bars=bars)

    def get_company_profile(self, symbol: str) -> CompanyProfile:
        info = self._info(self._ticker(symbol), symbol)
        location = ", ".join(str(part) for part in (info.get("city"), info.get("state"), info.get("country")) if part)
        return CompanyProfile(
            symbol=symbol,
            name=info.get("longName") or info.get("shortName"),
            description=info.get("longBusinessSummary"),
            sector=info.get("sector"),
            industry=info.get("industry"),
            exchange=info.get("fullExchangeName") or info.get("exchange"),
            country=info.get("country"),
            location=location or None,
            website=info.get("website"),
            employees=_int(info.get("fullTimeEmployees")),
            currency=info.get("currency"),
            market_cap=_num(info.get("marketCap")),
        )

    def get_key_metrics(self, symbol: str) -> KeyMetrics:
        info = self._info(self._ticker(symbol), symbol)
        return KeyMetrics(
            symbol=symbol,
            currency=info.get("currency") or info.get("financialCurrency"),
            market_cap=_num(info.get("marketCap")),
            enterprise_value=_num(info.get("enterpriseValue")),
            pe_ratio=_num(info.get("trailingPE")),
            forward_pe=_num(info.get("forwardPE")),
            peg_ratio=_num(info.get("trailingPegRatio") or info.get("pegRatio")),
            price_to_book=_num(info.get("priceToBook")),
            price_to_sales=_num(info.get("priceToSalesTrailing12Months")),
            ev_to_ebitda=_num(info.get("enterpriseToEbitda")),
            eps=_num(info.get("trailingEps")),
            # Yahoo reports dividendYield and debtToEquity in percent (0.35 == 0.35%,
            # 78.4 == 0.78x) while margins/growth/ROE are fractions. KeyMetrics uses
            # fractions throughout, so scale those two.
            dividend_yield=_pct_to_fraction(info.get("trailingAnnualDividendYield"), info.get("dividendYield")),
            beta=_num(info.get("beta")),
            gross_margin=_num(info.get("grossMargins")),
            operating_margin=_num(info.get("operatingMargins")),
            net_margin=_num(info.get("profitMargins")),
            return_on_equity=_num(info.get("returnOnEquity")),
            return_on_assets=_num(info.get("returnOnAssets")),
            revenue_growth=_num(info.get("revenueGrowth")),
            earnings_growth=_num(info.get("earningsGrowth")),
            debt_to_equity=_div100(info.get("debtToEquity")),
            current_ratio=_num(info.get("currentRatio")),
            free_cash_flow=_num(info.get("freeCashflow")),
            revenue=_num(info.get("totalRevenue")),
            ebitda=_num(info.get("ebitda")),
            fifty_two_week_high=_num(info.get("fiftyTwoWeekHigh")),
            fifty_two_week_low=_num(info.get("fiftyTwoWeekLow")),
            as_of=_now(),
        )

    def get_financials(
        self, symbol: str, statement: str = "income", period: str = "annual", limit: int = 4
    ) -> List[FinancialStatement]:
        if statement not in STATEMENTS:
            raise FinanceProviderError(f"statement must be one of {', '.join(STATEMENTS)}")
        if period not in STATEMENT_PERIODS:
            raise FinanceProviderError(f"period must be one of {', '.join(STATEMENT_PERIODS)}")
        attr = _STATEMENT_ATTRS[statement].get(period)
        if attr is None:
            raise FinanceProviderError(f"{period} {statement} is not available from Yahoo Finance")
        ticker = self._ticker(symbol)
        try:
            frame = getattr(ticker, attr)
        except Exception as e:
            raise FinanceProviderError(f"{statement} statement failed for {symbol}: {e}") from e
        if frame is None or getattr(frame, "empty", True):
            raise FinanceProviderError(f"No {period} {statement} statement for symbol {symbol}")

        currency: Optional[str] = None
        try:
            currency = self._info(ticker, symbol).get("financialCurrency")
        except Exception:
            log_debug(f"yfinance: could not read financial currency for {symbol}")

        # Columns are period-end timestamps (most recent first), rows are line items.
        statements: List[FinancialStatement] = []
        for column in list(frame.columns)[:limit]:
            series = frame[column]
            items: Dict[str, Any] = {}
            for line_item, value in series.items():
                number = _num(value)
                if number is not None:
                    items[_snake(str(line_item))] = number
            statements.append(
                FinancialStatement(
                    symbol=symbol,
                    statement=statement,
                    period=period,
                    report_period=_date(column),
                    currency=currency,
                    items=items,
                )
            )
        return statements

    def get_news(self, symbol: str, limit: int = 10) -> List[NewsItem]:
        ticker = self._ticker(symbol)
        try:
            raw = ticker.get_news(count=limit) if hasattr(ticker, "get_news") else ticker.news
        except TypeError:
            raw = ticker.news
        except Exception as e:
            raise FinanceProviderError(f"News failed for {symbol}: {e}") from e
        items: List[NewsItem] = []
        for entry in list(raw or [])[:limit]:
            item = _news_item(entry)
            if item is not None:
                items.append(item)
        return items

    def get_analyst_recommendations(self, symbol: str) -> AnalystRecommendations:
        ticker = self._ticker(symbol)
        result = AnalystRecommendations(symbol=symbol, as_of=_now())
        found = False

        try:
            summary = ticker.recommendations_summary
            if summary is not None and not getattr(summary, "empty", True):
                rows = summary.to_dict("records")
                current = next((r for r in rows if str(r.get("period", "")) in ("0m", "0")), rows[0])
                result.strong_buy = _int(current.get("strongBuy"))
                result.buy = _int(current.get("buy"))
                result.hold = _int(current.get("hold"))
                result.sell = _int(current.get("sell"))
                result.strong_sell = _int(current.get("strongSell"))
                counts = [c for c in (result.strong_buy, result.buy, result.hold, result.sell, result.strong_sell) if c]
                if counts:
                    result.num_analysts = sum(counts)
                    found = True
        except Exception as e:
            log_debug(f"yfinance: recommendations_summary failed for {symbol}: {e}")

        try:
            targets = ticker.analyst_price_targets
            if isinstance(targets, dict) and targets:
                result.target_mean = _num(targets.get("mean"))
                result.target_high = _num(targets.get("high"))
                result.target_low = _num(targets.get("low"))
                result.target_median = _num(targets.get("median"))
                result.current_price = _num(targets.get("current"))
                found = found or any(v is not None for v in (result.target_mean, result.target_high, result.target_low))
        except Exception as e:
            log_debug(f"yfinance: analyst_price_targets failed for {symbol}: {e}")

        try:
            info = ticker.info if isinstance(getattr(ticker, "info", None), dict) else {}
            key = info.get("recommendationKey")
            if key:
                result.consensus = str(key).replace("_", " ")
                found = True
            if result.num_analysts is None:
                result.num_analysts = _int(info.get("numberOfAnalystOpinions"))
            if result.target_mean is None:
                result.target_mean = _num(info.get("targetMeanPrice"))
                result.target_high = _num(info.get("targetHighPrice"))
                result.target_low = _num(info.get("targetLowPrice"))
                result.target_median = _num(info.get("targetMedianPrice"))
            if result.current_price is None:
                result.current_price = _num(info.get("regularMarketPrice") or info.get("currentPrice"))
        except Exception as e:
            log_debug(f"yfinance: info-based recommendation fields failed for {symbol}: {e}")

        if not found:
            raise FinanceProviderError(f"No analyst data for symbol {symbol}")
        return result

    def get_insider_trades(self, symbol: str, limit: int = 20) -> List[InsiderTrade]:
        ticker = self._ticker(symbol)
        try:
            frame = ticker.insider_transactions
        except Exception as e:
            raise FinanceProviderError(f"Insider transactions failed for {symbol}: {e}") from e
        if frame is None or getattr(frame, "empty", True):
            return []
        trades: List[InsiderTrade] = []
        for row in frame.to_dict("records")[:limit]:
            trades.append(
                InsiderTrade(
                    symbol=symbol,
                    insider=_str(row.get("Insider")),
                    title=_str(row.get("Position")),
                    transaction_type=_str(row.get("Transaction")) or _str(row.get("Text")),
                    transaction_date=_date(row.get("Start Date")),
                    shares=_num(row.get("Shares")),
                    value=_num(row.get("Value")),
                    url=_str(row.get("URL")),
                )
            )
        return trades

    def get_earnings(self, symbol: str, limit: int = 8) -> List[EarningsReport]:
        ticker = self._ticker(symbol)
        reports: List[EarningsReport] = []
        # earnings_dates includes the upcoming date (estimate only) but is scraped;
        # earnings_history is API-backed but past quarters only. Prefer the first, fall back.
        try:
            frame = ticker.get_earnings_dates(limit=limit) if hasattr(ticker, "get_earnings_dates") else None
        except Exception as e:
            log_debug(f"yfinance: earnings_dates failed for {symbol}: {e}")
            frame = None
        if frame is not None and not getattr(frame, "empty", True):
            for row in frame.reset_index().to_dict("records")[:limit]:
                date_key = next((k for k in row if "date" in str(k).lower()), None)
                reports.append(
                    EarningsReport(
                        symbol=symbol,
                        # Yahoo's earnings calendar is keyed by announcement time, not fiscal period end.
                        announced_at=_date(row.get(date_key)) if date_key else None,
                        eps=_num(row.get("Reported EPS")),
                        eps_estimate=_num(row.get("EPS Estimate")),
                        surprise_percent=_num(row.get("Surprise(%)")),
                    )
                )
            return reports

        try:
            history = ticker.earnings_history
        except Exception as e:
            raise FinanceProviderError(f"Earnings failed for {symbol}: {e}") from e
        if history is None or getattr(history, "empty", True):
            raise FinanceProviderError(f"No earnings data for symbol {symbol}")
        rows = history.reset_index().to_dict("records")
        rows.sort(key=lambda r: str(r.get("quarter", "")), reverse=True)
        for row in rows[:limit]:
            surprise = _num(row.get("surprisePercent"))
            reports.append(
                EarningsReport(
                    symbol=symbol,
                    report_period=_date(row.get("quarter")),
                    eps=_num(row.get("epsActual")),
                    eps_estimate=_num(row.get("epsEstimate")),
                    surprise_percent=round(surprise * 100, 4) if surprise is not None else None,
                )
            )
        return reports

    def get_sec_filings(self, symbol: str, form_type: Optional[str] = None, limit: int = 10) -> List[Filing]:
        ticker = self._ticker(symbol)
        try:
            raw = ticker.sec_filings
        except Exception as e:
            raise FinanceProviderError(f"SEC filings failed for {symbol}: {e}") from e
        filings: List[Filing] = []
        for entry in list(raw or []):
            if not isinstance(entry, dict):
                continue
            kind = _str(entry.get("type"))
            if form_type and (kind or "").upper() != form_type.upper():
                continue
            filings.append(
                Filing(
                    symbol=symbol,
                    form_type=kind,
                    filing_date=_date(entry.get("date")),
                    title=_str(entry.get("title")),
                    url=_str(entry.get("edgarUrl")),
                )
            )
            if len(filings) >= limit:
                break
        return filings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_STATEMENT_ATTRS: Dict[str, Dict[str, Optional[str]]] = {
    "income": {"annual": "income_stmt", "quarterly": "quarterly_income_stmt", "ttm": "ttm_income_stmt"},
    "balance_sheet": {"annual": "balance_sheet", "quarterly": "quarterly_balance_sheet", "ttm": None},
    "cash_flow": {"annual": "cash_flow", "quarterly": "quarterly_cash_flow", "ttm": "ttm_cash_flow"},
}


def _get(obj: Any, key: str) -> Any:
    """Read a key from a dict-like (`fast_info` raises KeyError for missing keys)."""
    try:
        return obj[key]
    except (KeyError, TypeError, AttributeError):
        pass
    getter = getattr(obj, "get", None)
    if callable(getter):
        try:
            return getter(key)
        except Exception:
            return None
    return None


def _num(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    if hasattr(value, "item"):
        try:
            value = value.item()
        except Exception:
            return None
    if isinstance(value, (int, float)):
        number = float(value)
        return None if math.isnan(number) or math.isinf(number) else number
    if isinstance(value, str):
        try:
            return float(value.replace(",", ""))
        except ValueError:
            return None
    return None


def _div100(value: Any) -> Optional[float]:
    number = _num(value)
    return number / 100 if number is not None else None


def _pct_to_fraction(fraction_value: Any, percent_value: Any) -> Optional[float]:
    """Prefer a field Yahoo already reports as a fraction, else scale the percent one."""
    fraction = _num(fraction_value)
    if fraction is not None:
        return fraction
    return _div100(percent_value)


def _int(value: Any) -> Optional[int]:
    number = _num(value)
    return int(number) if number is not None else None


def _str(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    text = str(value).strip()
    return text or None


def _date(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if math.isnan(value):
            return None
        return datetime.fromtimestamp(value, tz=timezone.utc).date().isoformat()
    if hasattr(value, "isoformat"):
        try:
            if hasattr(value, "date") and callable(value.date):
                # Keep the time when it carries information (intraday earnings dates), else the date.
                if getattr(value, "hour", 0) or getattr(value, "minute", 0):
                    return value.isoformat()
                return value.date().isoformat()
            return value.isoformat()
        except Exception:
            return str(value)
    return _str(value)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _snake(text: str) -> str:
    text = re.sub(r"[^0-9a-zA-Z]+", "_", text.strip())
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", text)
    return re.sub(r"_+", "_", text).strip("_").lower()


def _news_item(entry: Any) -> Optional[NewsItem]:
    """Normalize both the yfinance >= 0.2.50 shape ({"content": {...}}) and the legacy flat shape."""
    if not isinstance(entry, dict):
        return None
    content = entry.get("content") if isinstance(entry.get("content"), dict) else None
    if content is not None:
        provider = content.get("provider") if isinstance(content.get("provider"), dict) else {}
        url = None
        for key in ("canonicalUrl", "clickThroughUrl"):
            link = content.get(key)
            if isinstance(link, dict) and link.get("url"):
                url = link["url"]
                break
        title = _str(content.get("title"))
        if not title:
            return None
        return NewsItem(
            title=title,
            url=url,
            source=_str(provider.get("displayName")) if isinstance(provider, dict) else None,
            published_at=_str(content.get("pubDate") or content.get("displayTime")),
            summary=_str(content.get("summary") or content.get("description")),
        )
    title = _str(entry.get("title"))
    if not title:
        return None
    return NewsItem(
        title=title,
        url=_str(entry.get("link")),
        source=_str(entry.get("publisher")),
        published_at=_date(entry.get("providerPublishTime")),
        summary=None,
    )


__all__ = ["YFinance"]
