"""Unit tests for EurostatTools class."""

from unittest.mock import Mock, patch

import httpx
import pytest

from agno.tools.eurostat import EurostatTools


@pytest.fixture
def eurostat_tools():
    """Create an EurostatTools instance."""
    return EurostatTools()


def _mock_response(json_data, status_code=200):
    response = Mock()
    response.status_code = status_code
    response.json.return_value = json_data
    response.raise_for_status.return_value = None
    return response


def _jsonstat_payload():
    """A small, hand-built JSON-stat payload: unemployment rate for DE, two months.

    Dimensions (in `id` order): geo (1 value), time (2 values). Row-major flat
    index means index 0 -> (geo[0], time[0]), index 1 -> (geo[0], time[1]).
    """
    return {
        "label": "Unemployment rate",
        "source": "Eurostat",
        "id": ["geo", "time"],
        "size": [1, 2],
        "dimension": {
            "geo": {"category": {"index": {"DE": 0}, "label": {"DE": "Germany"}}},
            "time": {
                "category": {
                    "index": {"2026-01": 0, "2026-02": 1},
                    "label": {"2026-01": "2026-01", "2026-02": "2026-02"},
                }
            },
        },
        "value": {"0": 3.9, "1": 4.0},
    }


def test_init_registers_default_tools(eurostat_tools):
    """All three tools are registered by default."""
    names = [func.name for func in eurostat_tools.functions.values()]
    assert "list_indicators" in names
    assert "get_indicator" in names
    assert "get_dataset" in names


def test_init_with_selective_tools():
    """Only the enabled tools are registered."""
    tools = EurostatTools(enable_get_dataset=True, enable_get_indicator=False, enable_list_indicators=False)
    names = [func.name for func in tools.functions.values()]
    assert "get_dataset" in names
    assert "get_indicator" not in names
    assert "list_indicators" not in names


def test_list_indicators_returns_known_indicators(eurostat_tools):
    """list_indicators exposes the friendly-name shortcuts with their dataset codes."""
    result = eurostat_tools.list_indicators()
    assert "unemployment_rate" in result
    assert result["unemployment_rate"]["dataset"] == "une_rt_m"
    assert "gdp" in result
    assert "inflation_rate" in result
    assert "population" in result


def test_get_dataset_parses_jsonstat_into_records(eurostat_tools):
    """A JSON-stat response is unpacked into flat, labeled records."""
    with patch("agno.tools.eurostat.httpx.Client") as mock_client:
        client_instance = mock_client.return_value.__enter__.return_value
        client_instance.get.return_value = _mock_response(_jsonstat_payload())

        result = eurostat_tools.get_dataset("une_rt_m", geo="DE")

    assert result["title"] == "Unemployment rate"
    assert result["source"] == "Eurostat"
    assert len(result["records"]) == 2
    assert result["records"][0] == {"geo": "Germany", "time": "2026-01", "value": 3.9}
    assert result["records"][1] == {"geo": "Germany", "time": "2026-02", "value": 4.0}


def test_get_dataset_passes_geo_since_and_filters(eurostat_tools):
    """geo, since and filters all end up in the request params."""
    with patch("agno.tools.eurostat.httpx.Client") as mock_client:
        client_instance = mock_client.return_value.__enter__.return_value
        client_instance.get.return_value = _mock_response(_jsonstat_payload())

        eurostat_tools.get_dataset("une_rt_m", geo="DE", since="2026-01", filters={"sex": "T", "unit": "PC_ACT"})

        params = client_instance.get.call_args.kwargs["params"]

    assert params["geo"] == "DE"
    assert params["sinceTimePeriod"] == "2026-01"
    assert params["sex"] == "T"
    assert params["unit"] == "PC_ACT"
    assert params["format"] == "JSON"


def test_get_dataset_empty_result():
    """A response with no values returns an empty record list, not an error."""
    tools = EurostatTools()
    empty_payload = {"label": "Empty", "source": "Eurostat", "id": [], "size": [], "value": {}, "dimension": {}}
    with patch("agno.tools.eurostat.httpx.Client") as mock_client:
        client_instance = mock_client.return_value.__enter__.return_value
        client_instance.get.return_value = _mock_response(empty_payload)

        result = tools.get_dataset("some_empty_dataset")

    assert result["records"] == []


def test_get_indicator_unknown_name(eurostat_tools):
    """An unrecognized indicator name returns an error, no network call made."""
    result = eurostat_tools.get_indicator("not_a_real_indicator", geo="DE")
    assert "error" in result
    assert "Unknown indicator" in result["error"]


def test_get_indicator_delegates_to_get_dataset(eurostat_tools):
    """get_indicator resolves the friendly name to its dataset code and default filters."""
    with patch("agno.tools.eurostat.httpx.Client") as mock_client:
        client_instance = mock_client.return_value.__enter__.return_value
        client_instance.get.return_value = _mock_response(_jsonstat_payload())

        result = eurostat_tools.get_indicator("unemployment_rate", geo="DE", since="2026-01")

        call_url = client_instance.get.call_args.args[0]
        params = client_instance.get.call_args.kwargs["params"]

    assert call_url.endswith("/une_rt_m")
    assert params["geo"] == "DE"
    assert params["sinceTimePeriod"] == "2026-01"
    assert params["s_adj"] == "SA"
    assert result["records"][0]["value"] == 3.9


def test_http_error_handling(eurostat_tools):
    """HTTP status errors are mapped to friendly messages."""
    request = httpx.Request("GET", "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/une_rt_m")
    error_response = httpx.Response(status_code=404, request=request)

    def raise_error(*args, **kwargs):
        raise httpx.HTTPStatusError("not found", request=request, response=error_response)

    with patch("agno.tools.eurostat.httpx.Client") as mock_client:
        client_instance = mock_client.return_value.__enter__.return_value
        client_instance.get.side_effect = raise_error

        result = eurostat_tools.get_dataset("not_a_real_dataset")

    assert "error" in result
    assert "not found" in result["error"].lower() or "Dataset code not found" in result["error"]


def test_get_dataset_generic_exception(eurostat_tools):
    """A non-HTTP exception (e.g. connection error) is caught and reported."""
    with patch("agno.tools.eurostat.httpx.Client") as mock_client:
        client_instance = mock_client.return_value.__enter__.return_value
        client_instance.get.side_effect = Exception("Connection error")

        result = eurostat_tools.get_dataset("une_rt_m")

    assert "error" in result
    assert "Connection error" in result["error"]


@pytest.mark.asyncio
async def test_aget_dataset_success(eurostat_tools):
    """Async dataset fetch mirrors the sync behaviour."""

    async def async_get(*args, **kwargs):
        return _mock_response(_jsonstat_payload())

    with patch("agno.tools.eurostat.httpx.AsyncClient") as mock_client:
        client_instance = mock_client.return_value.__aenter__.return_value
        client_instance.get.side_effect = async_get

        result = await eurostat_tools.aget_dataset("une_rt_m", geo="DE")

    assert result["records"][0]["value"] == 3.9


@pytest.mark.asyncio
async def test_aget_indicator_unknown_name(eurostat_tools):
    """Async get_indicator also rejects unknown names without a network call."""
    result = await eurostat_tools.aget_indicator("not_a_real_indicator", geo="DE")
    assert "error" in result


@pytest.mark.asyncio
async def test_alist_indicators_matches_sync(eurostat_tools):
    """Async list_indicators returns the same content as the sync version."""
    result = await eurostat_tools.alist_indicators()
    assert result == eurostat_tools.list_indicators()
