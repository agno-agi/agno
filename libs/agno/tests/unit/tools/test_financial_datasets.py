import os
from unittest.mock import MagicMock, patch

import pytest

from agno.tools.financial_datasets import FinancialDatasetsTools


@pytest.fixture
def api_key():
    """Fixture for test API key."""
    return "test_api_key"


@pytest.fixture
def financial_tools(api_key):
    """Fixture for FinancialDatasetsTools instance."""
    return FinancialDatasetsTools(api_key=api_key)


@pytest.fixture
def mock_response():
    """Fixture for mocked API response."""
    response = MagicMock()
    response.json.return_value = {"status": "success", "data": []}
    response.raise_for_status.return_value = None
    return response


# Initialization Tests


def test_init_with_provided_key():
    """Test initialization with explicitly provided API key."""
    tools = FinancialDatasetsTools(api_key="explicit_key")
    assert tools.api_key == "explicit_key"


@patch.dict(os.environ, {"FINANCIAL_DATASETS_API_KEY": "env_key"})
def test_init_with_env_key():
    """Test initialization with API key from environment variable."""
    tools = FinancialDatasetsTools()
    assert tools.api_key == "env_key"


@patch("agno.tools.financial_datasets.log_error")
def test_init_without_key(mock_log_error):
    """Test initialization without API key."""
    # Clear environment variable if it exists
    with patch.dict(os.environ, {}, clear=True):
        tools = FinancialDatasetsTools()
        assert tools.api_key is None
        mock_log_error.assert_called_once()


# Financial Statements Endpoint Tests


@patch("agno.tools.financial_datasets.FinancialDatasetsTools._make_request")
def test_get_income_statements(mock_make_request, financial_tools):
    """Test get_income_statements method."""
    mock_make_request.return_value = {"income_statements": []}

    result = financial_tools.get_income_statements("AAPL", period="quarterly", limit=5)

    mock_make_request.assert_called_once_with(
        "financials/income-statements", {"ticker": "AAPL", "period": "quarterly", "limit": 5}
    )
    assert result == {"income_statements": []}


@patch("agno.tools.financial_datasets.FinancialDatasetsTools._make_request")
def test_get_balance_sheets(mock_make_request, financial_tools):
    """Test get_balance_sheets method."""
    mock_make_request.return_value = {"balance_sheets": []}

    result = financial_tools.get_balance_sheets("MSFT", period="annual", limit=3)

    mock_make_request.assert_called_once_with(
        "financials/balance-sheets", {"ticker": "MSFT", "period": "annual", "limit": 3}
    )
    assert result == {"balance_sheets": []}


@patch("agno.tools.financial_datasets.FinancialDatasetsTools._make_request")
def test_get_cash_flow_statements(mock_make_request, financial_tools):
    """Test get_cash_flow_statements method."""
    mock_make_request.return_value = {"cash_flow_statements": []}

    result = financial_tools.get_cash_flow_statements("GOOG", period="ttm", limit=1)

    mock_make_request.assert_called_once_with(
        "financials/cash-flow-statements", {"ticker": "GOOG", "period": "ttm", "limit": 1}
    )
    assert result == {"cash_flow_statements": []}


# Other API Endpoint Tests


@patch("agno.tools.financial_datasets.FinancialDatasetsTools._make_request")
def test_get_company_info(mock_make_request, financial_tools):
    """Test get_company_info method."""
    mock_make_request.return_value = {"company": {}}

    result = financial_tools.get_company_info("AMZN")

    mock_make_request.assert_called_once_with("company", {"ticker": "AMZN"})
    assert result == {"company": {}}


@patch("agno.tools.financial_datasets.FinancialDatasetsTools._make_request")
def test_get_crypto_prices(mock_make_request, financial_tools):
    """Test get_crypto_prices method."""
    mock_make_request.return_value = {"prices": []}

    result = financial_tools.get_crypto_prices("BTC", interval="1h", limit=24)

    mock_make_request.assert_called_once_with("crypto/prices", {"symbol": "BTC", "interval": "1h", "limit": 24})
    assert result == {"prices": []}


@patch("agno.tools.financial_datasets.FinancialDatasetsTools._make_request")
def test_get_earnings(mock_make_request, financial_tools):
    """Test get_earnings method."""
    mock_make_request.return_value = {"earnings": []}

    result = financial_tools.get_earnings("TSLA", limit=8)

    mock_make_request.assert_called_once_with("earnings", {"ticker": "TSLA", "limit": 8})
    assert result == {"earnings": []}


@patch("agno.tools.financial_datasets.FinancialDatasetsTools._make_request")
def test_get_financial_metrics(mock_make_request, financial_tools):
    """Test get_financial_metrics method."""
    mock_make_request.return_value = {"metrics": {}}

    result = financial_tools.get_financial_metrics("FB")

    mock_make_request.assert_called_once_with("financials/metrics", {"ticker": "FB"})
    assert result == {"metrics": {}}


@patch("agno.tools.financial_datasets.FinancialDatasetsTools._make_request")
def test_get_insider_trades(mock_make_request, financial_tools):
    """Test get_insider_trades method."""
    mock_make_request.return_value = {"insider_trades": []}

    result = financial_tools.get_insider_trades("NFLX", limit=25)

    mock_make_request.assert_called_once_with("insider-trades", {"ticker": "NFLX", "limit": 25})
    assert result == {"insider_trades": []}


@patch("agno.tools.financial_datasets.FinancialDatasetsTools._make_request")
def test_get_institutional_ownership(mock_make_request, financial_tools):
    """Test get_institutional_ownership method."""
    mock_make_request.return_value = {"ownership": []}

    result = financial_tools.get_institutional_ownership("INTC")

    mock_make_request.assert_called_once_with("institutional-ownership", {"ticker": "INTC"})
    assert result == {"ownership": []}


@patch("agno.tools.financial_datasets.FinancialDatasetsTools._make_request")
def test_get_news_with_ticker(mock_make_request, financial_tools):
    """Test get_news method with ticker."""
    mock_make_request.return_value = {"news": []}

    result = financial_tools.get_news(ticker="NVDA", limit=15)

    mock_make_request.assert_called_once_with("news", {"ticker": "NVDA", "limit": 15})
    assert result == {"news": []}


@patch("agno.tools.financial_datasets.FinancialDatasetsTools._make_request")
def test_get_news_without_ticker(mock_make_request, financial_tools):
    """Test get_news method without ticker."""
    mock_make_request.return_value = {"news": []}

    result = financial_tools.get_news(limit=30)

    mock_make_request.assert_called_once_with("news", {"limit": 30})
    assert result == {"news": []}


@patch("agno.tools.financial_datasets.FinancialDatasetsTools._make_request")
def test_get_stock_prices(mock_make_request, financial_tools):
    """Test get_stock_prices method."""
    mock_make_request.return_value = {"prices": []}

    result = financial_tools.get_stock_prices("AAPL", interval="1h", limit=48)

    mock_make_request.assert_called_once_with("prices", {"ticker": "AAPL", "interval": "1h", "limit": 48})
    assert result == {"prices": []}


@patch("agno.tools.financial_datasets.FinancialDatasetsTools._make_request")
def test_search_tickers(mock_make_request, financial_tools):
    """Test search_tickers method."""
    mock_make_request.return_value = {"results": []}

    result = financial_tools.search_tickers("apple", limit=5)

    mock_make_request.assert_called_once_with("search", {"query": "apple", "limit": 5})
    assert result == {"results": []}


@patch("agno.tools.financial_datasets.FinancialDatasetsTools._make_request")
def test_get_sec_filings_with_form_type(mock_make_request, financial_tools):
    """Test get_sec_filings method with form type."""
    mock_make_request.return_value = {"filings": []}

    result = financial_tools.get_sec_filings("AAPL", form_type="10-K", limit=10)

    mock_make_request.assert_called_once_with("sec-filings", {"ticker": "AAPL", "form_type": "10-K", "limit": 10})
    assert result == {"filings": []}


@patch("agno.tools.financial_datasets.FinancialDatasetsTools._make_request")
def test_get_sec_filings_without_form_type(mock_make_request, financial_tools):
    """Test get_sec_filings method without form type."""
    mock_make_request.return_value = {"filings": []}

    result = financial_tools.get_sec_filings("MSFT", limit=20)

    mock_make_request.assert_called_once_with("sec-filings", {"ticker": "MSFT", "limit": 20})
    assert result == {"filings": []}


@patch("agno.tools.financial_datasets.FinancialDatasetsTools._make_request")
def test_get_segmented_financials(mock_make_request, financial_tools):
    """Test get_segmented_financials method."""
    mock_make_request.return_value = {"segmented_financials": []}

    result = financial_tools.get_segmented_financials("GOOG", period="quarterly", limit=4)

    mock_make_request.assert_called_once_with(
        "financials/segmented", {"ticker": "GOOG", "period": "quarterly", "limit": 4}
    )
    assert result == {"segmented_financials": []}
