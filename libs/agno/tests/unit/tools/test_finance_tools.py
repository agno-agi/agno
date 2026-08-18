"""FinanceTools: tool registration by capability, provider resolution, JSON envelope, async variants."""

import json
import math
from typing import List, Optional
from unittest.mock import patch

import pytest

from agno.tools.finance import (
    ALL_CAPABILITIES,
    FinanceProvider,
    FinanceProviderError,
    FinanceTools,
    FinancialDatasetsProvider,
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
from agno.tools.finance.base import GET_NEWS, GET_QUOTE, SEARCH_SYMBOLS

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeProvider(FinanceProvider):
    """Serves quote + news + search only, records calls, can be told to fail."""

    id = "fake"
    name = "Fake Market Data"
    capabilities = frozenset({GET_QUOTE, GET_NEWS, SEARCH_SYMBOLS})

    def __init__(self, fail_with: Optional[Exception] = None):
        self.calls: List[tuple] = []
        self.fail_with = fail_with

    def status(self) -> ProviderStatus:
        return ProviderStatus(ok=True, detail="fake")

    def search_symbols(self, query: str, limit: int = 5) -> List[SymbolMatch]:
        self.calls.append(("search_symbols", query, limit))
        return [SymbolMatch(symbol="NVDA", name="NVIDIA Corporation", exchange="NASDAQ", type="EQUITY")]

    def get_quote(self, symbol: str) -> Quote:
        self.calls.append(("get_quote", symbol))
        if self.fail_with:
            raise self.fail_with
        return Quote(
            symbol=symbol,
            price=225.0123456,
            currency="USD",
            change=-0.14,
            change_percent=float("nan"),
            volume=None,
            as_of="2026-08-18T11:00:00+00:00",
        )

    def get_news(self, symbol: str, limit: int = 10) -> List[NewsItem]:
        self.calls.append(("get_news", symbol, limit))
        return [NewsItem(title="Headline", url="https://example.test/a", source="Wire", published_at="2026-08-18")]


class AsyncFakeProvider(FakeProvider):
    """Native async override to prove the toolkit dispatches to `aget_*`."""

    async def aget_quote(self, symbol: str) -> Quote:
        self.calls.append(("aget_quote", symbol))
        return Quote(symbol=symbol, price=1.0, currency="USD")


class HistoryProvider(FinanceProvider):
    id = "hist"
    name = "History Only"
    capabilities = frozenset({"get_price_history"})

    def get_price_history(self, symbol: str, period: str = "1mo", interval: str = "1d") -> PriceHistory:
        return PriceHistory(
            symbol=symbol,
            period=period,
            interval=interval,
            currency="USD",
            bars=[PriceBar(date="2026-08-17", open=1.0, high=2.0, low=0.5, close=1.5, volume=10)],
        )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_registers_only_supported_tools_sync_and_async():
    tools = FinanceTools(provider=FakeProvider(), all=True)

    assert list(tools.functions) == ["search_symbols", "get_quote", "get_news"]
    assert set(tools.async_functions) == set(tools.functions)
    assert tools.registered_tools == ["search_symbols", "get_quote", "get_news"]
    assert tools.name == "finance_tools"


def test_default_toggles_register_core_tools_only():
    tools = FinanceTools(provider=FinancialDatasetsProvider(api_key="k"))

    # financial_datasets lacks search_symbols / get_analyst_recommendations; long-tail tools are off by default
    assert list(tools.functions) == [
        "get_quote",
        "get_price_history",
        "get_company_profile",
        "get_key_metrics",
        "get_news",
    ]


def test_all_flag_registers_long_tail_tools():
    tools = FinanceTools(provider=FinancialDatasetsProvider(api_key="k"), all=True)

    assert list(tools.functions) == [
        "get_quote",
        "get_price_history",
        "get_company_profile",
        "get_key_metrics",
        "get_news",
        "get_financials",
        "get_insider_trades",
        "get_earnings",
        "get_sec_filings",
    ]


def test_toggle_off_removes_tool_and_include_tools_still_works():
    tools = FinanceTools(provider=FakeProvider(), news=False)
    assert "get_news" not in tools.functions
    assert "get_quote" in tools.functions

    only_quote = FinanceTools(provider=FakeProvider(), include_tools=["get_quote"])
    assert list(only_quote.functions) == ["get_quote"]
    assert list(only_quote.async_functions) == ["get_quote"]


def test_include_tools_enables_off_by_default_tools():
    tools = FinanceTools(provider=FinancialDatasetsProvider(api_key="k"), include_tools=["get_quote", "get_financials"])
    assert list(tools.functions) == ["get_quote", "get_financials"]
    assert list(tools.async_functions) == ["get_quote", "get_financials"]

    # A tool the provider cannot serve still fails the Toolkit include check with a clear message
    with pytest.raises(ValueError, match="Included tool\\(s\\) not present in the toolkit: search_symbols"):
        FinanceTools(provider=FinancialDatasetsProvider(api_key="k"), include_tools=["search_symbols"])


def test_all_capabilities_are_exactly_the_tool_names():
    tools = FinanceTools(provider=FinancialDatasetsProvider(api_key="k"), all=True)
    # Every capability name must resolve to a method on the toolkit (sync + async)
    for capability in ALL_CAPABILITIES:
        assert callable(getattr(tools, capability))
        assert callable(getattr(tools, f"a{capability}"))


def test_instructions_list_registered_tools_only():
    tools = FinanceTools(provider=FakeProvider(), news=False)

    assert tools.add_instructions is True
    assert tools.instructions is not None
    assert "`get_quote`" in tools.instructions
    assert "`get_news`" not in tools.instructions
    assert "Fake Market Data" in tools.instructions
    assert "search_symbols" in tools.instructions  # provider supports it, so the guideline mentions it


def test_instructions_can_be_overridden():
    tools = FinanceTools(provider=FakeProvider(), instructions="custom", add_instructions=False)

    assert tools.instructions == "custom"
    assert tools.add_instructions is False


def test_status_delegates_to_provider():
    tools = FinanceTools(provider=FakeProvider())

    assert tools.status() == ProviderStatus(ok=True, detail="fake")


def test_repr_names_provider_and_tools():
    text = repr(FinanceTools(provider=FakeProvider()))

    assert "provider=fake" in text
    assert "get_quote" in text


# ---------------------------------------------------------------------------
# Provider resolution
# ---------------------------------------------------------------------------


def test_string_provider_resolves_via_registry_and_forwards_timeout():
    tools = FinanceTools(provider="financial_datasets", timeout=7, all=True)

    assert isinstance(tools.provider, FinancialDatasetsProvider)
    assert tools.provider.timeout == 7
    assert "financial_datasets" in registered_providers()
    assert "yfinance" in registered_providers()


def test_unknown_string_provider_raises():
    with pytest.raises(ValueError, match="Unknown finance provider 'nope'"):
        FinanceTools(provider="nope")


def test_wrong_provider_type_raises():
    with pytest.raises(TypeError):
        FinanceTools(provider=123)  # type: ignore[arg-type]


def test_none_provider_prefers_yfinance_when_importable():
    fake = FakeProvider()
    with patch("agno.tools.finance.toolkit._yfinance_importable", return_value=True):
        with patch(
            "agno.tools.finance.toolkit._get_registered_provider",
            side_effect=lambda pid: (lambda **kw: fake) if pid == "yfinance" else None,
        ):
            tools = FinanceTools()
    assert tools.provider is fake


def test_none_provider_falls_back_to_financial_datasets_when_key_set():
    with patch("agno.tools.finance.toolkit._yfinance_importable", return_value=False):
        with patch.dict("os.environ", {"FINANCIAL_DATASETS_API_KEY": "k"}):
            tools = FinanceTools()
    assert isinstance(tools.provider, FinancialDatasetsProvider)


def test_none_provider_without_any_option_raises_helpful_import_error():
    with patch("agno.tools.finance.toolkit._yfinance_importable", return_value=False):
        with patch.dict("os.environ", {}, clear=False):
            import os

            os.environ.pop("FINANCIAL_DATASETS_API_KEY", None)
            with pytest.raises(ImportError, match="pip install yfinance"):
                FinanceTools()


def test_timeout_is_ignored_with_warning_for_instances():
    with patch("agno.tools.finance.toolkit.log_warning") as warn:
        FinanceTools(provider=FakeProvider(), timeout=3)
    assert warn.called


def test_register_provider_custom_id():
    register_provider("fake_registered", FakeProvider)
    tools = FinanceTools(provider="fake_registered")

    assert isinstance(tools.provider, FakeProvider)
    with pytest.raises(ValueError):
        register_provider("", FakeProvider)


# ---------------------------------------------------------------------------
# JSON envelope
# ---------------------------------------------------------------------------


def test_quote_payload_is_compact_rounded_and_tagged():
    provider = FakeProvider()
    tools = FinanceTools(provider=provider)

    payload = json.loads(tools.get_quote(" nvda "))

    assert provider.calls == [("get_quote", "NVDA")]  # upper-cased + stripped
    assert payload["symbol"] == "NVDA"
    assert payload["price"] == 225.0123  # rounded to 4 dp
    assert payload["provider"] == "fake"
    assert "volume" not in payload  # None dropped
    assert "change_percent" not in payload  # NaN dropped
    assert payload["as_of"] == "2026-08-18T11:00:00+00:00"


def test_list_payload_wraps_results_with_context():
    provider = FakeProvider()
    tools = FinanceTools(provider=provider)

    payload = json.loads(tools.get_news("nvda", limit=3))

    assert provider.calls == [("get_news", "NVDA", 3)]
    assert payload["symbol"] == "NVDA"
    assert payload["provider"] == "fake"
    assert payload["results"] == [
        {"title": "Headline", "url": "https://example.test/a", "source": "Wire", "published_at": "2026-08-18"}
    ]


def test_search_payload_echoes_query():
    tools = FinanceTools(provider=FakeProvider())

    payload = json.loads(tools.search_symbols("  NVIDIA "))
    assert payload["query"] == "NVIDIA"
    assert payload["results"][0]["symbol"] == "NVDA"


def test_nested_dataclass_payload_for_price_history():
    tools = FinanceTools(provider=HistoryProvider())

    payload = json.loads(tools.get_price_history("nvda", period="5d", interval="1wk"))
    assert payload["period"] == "5d" and payload["interval"] == "1wk"
    assert payload["bars"] == [{"date": "2026-08-17", "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 10}]
    assert payload["provider"] == "hist"


def test_limit_is_clamped_and_defaulted():
    provider = FakeProvider()
    tools = FinanceTools(provider=provider)

    tools.get_news("NVDA", limit=10_000)
    tools.get_news("NVDA", limit=0)
    tools.get_news("NVDA", limit="abc")  # type: ignore[arg-type]

    assert [c[2] for c in provider.calls] == [50, 1, 10]


# ---------------------------------------------------------------------------
# Errors and validation
# ---------------------------------------------------------------------------


def test_provider_error_becomes_error_payload_not_exception():
    tools = FinanceTools(provider=FakeProvider(fail_with=FinanceProviderError("No quote data for symbol NVDA")))

    payload = json.loads(tools.get_quote("NVDA"))
    assert payload == {"symbol": "NVDA", "error": "No quote data for symbol NVDA", "provider": "fake"}


def test_unexpected_exception_is_wrapped_with_type_name():
    tools = FinanceTools(provider=FakeProvider(fail_with=RuntimeError("boom")))

    payload = json.loads(tools.get_quote("NVDA"))
    assert payload["error"] == "RuntimeError: boom"


def test_not_supported_error_message():
    err = FakeProvider()._not_supported("get_earnings")
    assert isinstance(err, NotSupportedError)
    assert "does not support get_earnings" in str(err)


def test_empty_symbol_is_rejected_before_provider_call():
    provider = FakeProvider()
    tools = FinanceTools(provider=provider)

    payload = json.loads(tools.get_quote("   "))
    assert payload == {"error": "symbol is required", "provider": "fake"}
    assert provider.calls == []


def test_empty_query_is_rejected():
    tools = FinanceTools(provider=FakeProvider())
    assert json.loads(tools.search_symbols(""))["error"] == "query is required"


def test_enum_params_validated_before_provider_call():
    tools = FinanceTools(provider=HistoryProvider())

    bad_period = json.loads(tools.get_price_history("NVDA", period="7d"))
    assert bad_period["error"].startswith("period must be one of 1d, 5d, 1mo")
    assert bad_period["symbol"] == "NVDA"

    bad_interval = json.loads(tools.get_price_history("NVDA", interval="1h"))
    assert bad_interval["error"].startswith("interval must be one of 1d, 1wk, 1mo")


def test_financials_enum_validation():
    tools = FinanceTools(provider=FinancialDatasetsProvider(api_key="k"), all=True)

    assert json.loads(tools.get_financials("NVDA", statement="revenue"))["error"].startswith("statement must be one of")
    assert json.loads(tools.get_financials("NVDA", period="monthly"))["error"].startswith("period must be one of")


# ---------------------------------------------------------------------------
# Async
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_variants_dispatch_to_provider_async_methods():
    provider = AsyncFakeProvider()
    tools = FinanceTools(provider=provider)

    payload = json.loads(await tools.aget_quote("nvda"))
    assert payload["price"] == 1.0
    assert provider.calls == [("aget_quote", "NVDA")]


@pytest.mark.asyncio
async def test_async_default_falls_back_to_sync_in_thread():
    provider = FakeProvider()
    tools = FinanceTools(provider=provider)

    payload = json.loads(await tools.aget_news("NVDA", limit=2))
    assert payload["results"][0]["title"] == "Headline"
    assert provider.calls == [("get_news", "NVDA", 2)]

    news = json.loads(await tools.asearch_symbols("NVIDIA"))
    assert news["results"][0]["symbol"] == "NVDA"


@pytest.mark.asyncio
async def test_async_error_envelope_and_validation():
    tools = FinanceTools(provider=FakeProvider(fail_with=FinanceProviderError("nope")))

    assert json.loads(await tools.aget_quote("NVDA"))["error"] == "nope"
    assert json.loads(await tools.aget_quote(""))["error"] == "symbol is required"


@pytest.mark.asyncio
async def test_registered_async_functions_share_schema_with_sync():
    tools = FinanceTools(provider=FinancialDatasetsProvider(api_key="k"), all=True)
    for name, sync_fn in tools.get_functions().items():
        async_fn = tools.get_async_functions()[name]
        sync_fn.process_entrypoint()
        async_fn.process_entrypoint()
        assert sync_fn.to_dict()["description"] == async_fn.to_dict()["description"], name
        assert sync_fn.to_dict()["parameters"] == async_fn.to_dict()["parameters"], name


def test_clean_helper_handles_numpy_like_scalars_and_timestamps():
    from datetime import date

    from agno.tools.finance.toolkit import _clean

    class Scalar:
        def item(self):
            return 3

    assert _clean(
        {"a": None, "b": Scalar(), "c": date(2026, 8, 18), "d": float("inf"), "e": True, "f": (1.23456,)}
    ) == {
        "b": 3,
        "c": "2026-08-18",
        "e": True,
        "f": [1.2346],
    }
    assert math.isnan(float("nan"))  # sanity: NaN dropped path exercised above via provider
