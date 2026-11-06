"""Unit tests for JsonifyTools class."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.tools.jsonify import JsonifyTools

SERVE_URL = "https://factory.jsonify.com/api/serve/abc123"

SERVE_RESPONSE = {
    "dataset": "abc123",
    "dataset_name": "Competitor watch",
    "table": "competitor_changes",
    "integration": "rest_api",
    "version": 12,
    "updated_at": 1760400000,
    "row_count": 2,
    "has_more": True,
    "next_offset": 2,
    "rows": [
        {
            "_row_id": "r1",
            "_parent_row_id": "p1",
            "_source_key": "klue",
            "competitor": "Klue",
            "page": "homepage",
            "changed": "no",
        },
        {
            "_row_id": "r2",
            "_parent_row_id": "p2",
            "_source_key": "crayon",
            "competitor": "Crayon",
            "page": "pricing",
            "changed": "yes",
        },
    ],
}


def _mock_response(payload):
    response = MagicMock()
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    return response


@pytest.fixture
def jsonify_tools():
    return JsonifyTools(datasets=SERVE_URL)


class TestJsonifyToolsInitialization:
    def test_single_url_registers_both_tools(self, jsonify_tools):
        function_names = [func.name for func in jsonify_tools.functions.values()]
        assert "get_jsonify_rows" in function_names
        assert "get_jsonify_dataset_info" in function_names
        assert jsonify_tools.name == "jsonify_tools"
        assert jsonify_tools.datasets == {"default": SERVE_URL}

    def test_async_variants_registered(self, jsonify_tools):
        async_names = list(jsonify_tools.async_functions.keys())
        assert "get_jsonify_rows" in async_names
        assert "get_jsonify_dataset_info" in async_names

    def test_env_var_fallback(self):
        with patch.dict("os.environ", {"JSONIFY_SERVE_URL": SERVE_URL}, clear=True):
            tools = JsonifyTools()
            assert tools.datasets == {"default": SERVE_URL}

    def test_missing_url_raises(self):
        with patch.dict("os.environ", {}, clear=True), pytest.raises(ValueError):
            JsonifyTools()

    def test_rows_only(self):
        tools = JsonifyTools(datasets=SERVE_URL, enable_get_dataset_info=False)
        function_names = [func.name for func in tools.functions.values()]
        assert function_names == ["get_jsonify_rows"]

    def test_all_flag_overrides(self):
        tools = JsonifyTools(datasets=SERVE_URL, enable_get_rows=False, enable_get_dataset_info=False, all=True)
        function_names = [func.name for func in tools.functions.values()]
        assert "get_jsonify_rows" in function_names
        assert "get_jsonify_dataset_info" in function_names


class TestGetRows:
    def test_get_rows_builds_params_and_formats(self, jsonify_tools):
        with patch("agno.tools.jsonify.httpx.get", return_value=_mock_response(SERVE_RESPONSE)) as mock_get:
            result = json.loads(
                jsonify_tools.get_jsonify_rows(
                    limit=2,
                    offset=0,
                    columns=["_row_id", "competitor"],
                    filters={"changed": "yes"},
                    version=12,
                )
            )

        _, kwargs = mock_get.call_args
        assert mock_get.call_args[0][0] == SERVE_URL
        assert kwargs["params"] == {
            "limit": 2,
            "offset": 0,
            "columns": "_row_id,competitor",
            "version": 12,
            "filter[changed]": "yes",
        }
        assert kwargs["timeout"] == 30

        assert result["dataset_name"] == "Competitor watch"
        assert result["version"] == 12
        assert result["row_count"] == 2
        assert result["has_more"] is True
        assert result["next_offset"] == 2
        assert [r["competitor"] for r in result["rows"]] == ["Klue", "Crayon"]

    def test_named_dataset(self):
        tools = JsonifyTools(datasets={"watch": SERVE_URL, "other": SERVE_URL + "0"})
        with patch("agno.tools.jsonify.httpx.get", return_value=_mock_response(SERVE_RESPONSE)) as mock_get:
            tools.get_jsonify_rows(dataset="other")
        assert mock_get.call_args[0][0] == SERVE_URL + "0"

    def test_ambiguous_dataset_returns_error(self):
        tools = JsonifyTools(datasets={"a": SERVE_URL, "b": SERVE_URL + "0"})
        result = tools.get_jsonify_rows()
        assert result.startswith("Error reading Jsonify dataset")

    def test_unknown_dataset_returns_error(self, jsonify_tools):
        result = jsonify_tools.get_jsonify_rows(dataset="missing")
        assert "Unknown dataset" in result

    def test_http_error_returns_error(self, jsonify_tools):
        response = MagicMock()
        response.raise_for_status.side_effect = Exception("404 Not Found")
        with patch("agno.tools.jsonify.httpx.get", return_value=response):
            result = jsonify_tools.get_jsonify_rows()
        assert "404" in result


class TestGetDatasetInfo:
    def test_info_lists_public_columns(self, jsonify_tools):
        with patch("agno.tools.jsonify.httpx.get", return_value=_mock_response(SERVE_RESPONSE)) as mock_get:
            result = json.loads(jsonify_tools.get_jsonify_dataset_info())

        assert mock_get.call_args[1]["params"] == {"limit": 1}
        assert result["dataset_name"] == "Competitor watch"
        assert result["table"] == "competitor_changes"
        assert result["version"] == 12
        assert result["columns"] == ["_row_id", "competitor", "page", "changed"]

    def test_info_empty_dataset(self, jsonify_tools):
        payload = dict(SERVE_RESPONSE, rows=[], row_count=0)
        with patch("agno.tools.jsonify.httpx.get", return_value=_mock_response(payload)):
            result = json.loads(jsonify_tools.get_jsonify_dataset_info())
        assert result["columns"] == []


class TestAsync:
    @pytest.mark.asyncio
    async def test_aget_rows(self, jsonify_tools):
        client = MagicMock()
        client.get = AsyncMock(return_value=_mock_response(SERVE_RESPONSE))
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)
        with patch("agno.tools.jsonify.httpx.AsyncClient", return_value=client):
            result = json.loads(await jsonify_tools.aget_jsonify_rows(filters={"competitor": "Klue"}))

        _, kwargs = client.get.call_args
        assert kwargs["params"]["filter[competitor]"] == "Klue"
        assert result["version"] == 12

    @pytest.mark.asyncio
    async def test_aget_info(self, jsonify_tools):
        client = MagicMock()
        client.get = AsyncMock(return_value=_mock_response(SERVE_RESPONSE))
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)
        with patch("agno.tools.jsonify.httpx.AsyncClient", return_value=client):
            result = json.loads(await jsonify_tools.aget_jsonify_dataset_info())
        assert result["columns"] == ["_row_id", "competitor", "page", "changed"]
