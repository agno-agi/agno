import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from agno.tools.n8n import N8nTools


class TestN8nTools:
    @pytest.fixture
    def n8n_tools(self):
        tools = N8nTools(base_url="http://n8n.local:5678", api_key="test-key")
        return tools

    # ---- Init tests ----

    def test_init_with_explicit_params(self):
        tools = N8nTools(base_url="http://n8n.local:5678", api_key="my-key", timeout=60)

        assert tools.base_url == "http://n8n.local:5678"
        assert tools.api_key == "my-key"
        assert tools.timeout == 60

    def test_init_strips_trailing_slash(self):
        tools = N8nTools(base_url="http://n8n.local:5678/", api_key="key")

        assert tools.base_url == "http://n8n.local:5678"

    def test_init_uses_environment_variable(self):
        with patch.dict(os.environ, {"N8N_API_KEY": "env-key"}):
            tools = N8nTools(base_url="http://localhost:5678")

        assert tools.api_key == "env-key"

    def test_init_without_key_logs_warning(self):
        with patch.dict(os.environ, {}, clear=True):
            tools = N8nTools(base_url="http://localhost:5678", api_key=None)

        assert tools.api_key is None

    # ---- Flag registration tests ----

    def test_all_tools_registered_by_default(self):
        tools = N8nTools(base_url="http://localhost:5678", api_key="key")

        assert set(tools.functions.keys()) == {
            "list_workflows",
            "get_workflow",
            "activate_workflow",
            "deactivate_workflow",
            "list_executions",
            "get_execution",
            "delete_execution",
        }
        assert set(tools.async_functions.keys()) == set(tools.functions.keys())

    def test_enable_flags_register_selected_tools_only(self):
        tools = N8nTools(
            base_url="http://localhost:5678",
            api_key="key",
            enable_list_workflows=True,
            enable_get_workflow=True,
            enable_activate_workflow=False,
            enable_deactivate_workflow=False,
            enable_list_executions=False,
            enable_get_execution=False,
            enable_delete_execution=False,
        )

        assert set(tools.functions.keys()) == {"list_workflows", "get_workflow"}
        assert set(tools.async_functions.keys()) == {"list_workflows", "get_workflow"}

    def test_all_flag_overrides_individual_flags(self):
        tools = N8nTools(
            base_url="http://localhost:5678",
            api_key="key",
            all=True,
            enable_list_workflows=False,
            enable_get_workflow=False,
        )

        assert len(tools.functions) == 7
        assert len(tools.async_functions) == 7

    def test_no_flags_registers_nothing(self):
        tools = N8nTools(
            base_url="http://localhost:5678",
            api_key="key",
            enable_list_workflows=False,
            enable_get_workflow=False,
            enable_activate_workflow=False,
            enable_deactivate_workflow=False,
            enable_list_executions=False,
            enable_get_execution=False,
            enable_delete_execution=False,
        )

        assert len(tools.functions) == 0
        assert len(tools.async_functions) == 0

    def test_async_tools_registered_with_sync_names(self):
        tools = N8nTools(base_url="http://localhost:5678", api_key="key")

        assert "list_workflows" in tools.async_functions
        assert "alist_workflows" not in tools.async_functions

    # ---- Helper tests ----

    def test_build_url(self, n8n_tools):
        assert n8n_tools._build_url("/workflows") == "http://n8n.local:5678/api/v1/workflows"
        assert n8n_tools._build_url("/workflows/abc") == "http://n8n.local:5678/api/v1/workflows/abc"
        assert n8n_tools._build_url("/executions") == "http://n8n.local:5678/api/v1/executions"

    def test_build_headers_with_key(self, n8n_tools):
        headers = n8n_tools._build_headers()

        assert headers["X-N8N-API-KEY"] == "test-key"
        assert headers["Accept"] == "application/json"

    def test_build_headers_without_key(self):
        with patch.dict(os.environ, {}, clear=True):
            tools = N8nTools(base_url="http://localhost:5678", api_key=None)

        headers = tools._build_headers()
        assert "X-N8N-API-KEY" not in headers
        assert headers["Accept"] == "application/json"

    def test_json_error(self, n8n_tools):
        result = json.loads(n8n_tools._json_error("something broke"))

        assert result == {"error": "something broke"}

    def test_http_error_message_json_body(self, n8n_tools):
        response = httpx.Response(
            status_code=401,
            json={"message": "unauthorized"},
            request=httpx.Request("GET", "http://n8n.local:5678/api/v1/workflows"),
        )

        assert n8n_tools._http_error_message(response) == "401: unauthorized"

    def test_http_error_message_plain_text(self, n8n_tools):
        response = httpx.Response(
            status_code=500,
            text="Internal Server Error",
            request=httpx.Request("GET", "http://n8n.local:5678/api/v1/workflows"),
        )

        assert n8n_tools._http_error_message(response) == "500: Internal Server Error"

    # ---- Sync method tests ----

    @patch("agno.tools.n8n.httpx.get")
    def test_list_workflows_success(self, mock_get, n8n_tools):
        mock_get.return_value = httpx.Response(
            status_code=200,
            json={"data": [{"id": "wf1", "name": "My WF", "active": True}], "nextCursor": None},
            request=httpx.Request("GET", "http://n8n.local:5678/api/v1/workflows"),
        )

        result = json.loads(n8n_tools.list_workflows())

        assert result["count"] == 1
        assert result["data"][0]["name"] == "My WF"
        assert result["nextCursor"] is None

    @patch("agno.tools.n8n.httpx.get")
    def test_list_workflows_active_only(self, mock_get, n8n_tools):
        mock_get.return_value = httpx.Response(
            status_code=200,
            json={
                "data": [
                    {"id": "wf1", "name": "Active", "active": True},
                    {"id": "wf2", "name": "Inactive", "active": False},
                ],
                "nextCursor": None,
            },
            request=httpx.Request("GET", "http://n8n.local:5678/api/v1/workflows"),
        )

        result = json.loads(n8n_tools.list_workflows(active_only=True))

        assert result["count"] == 1
        assert result["data"][0]["name"] == "Active"

    @patch("agno.tools.n8n.httpx.get")
    def test_list_workflows_with_pagination(self, mock_get, n8n_tools):
        mock_get.return_value = httpx.Response(
            status_code=200,
            json={"data": [{"id": "wf1", "name": "WF", "active": True}], "nextCursor": "abc123"},
            request=httpx.Request("GET", "http://n8n.local:5678/api/v1/workflows"),
        )

        result = json.loads(n8n_tools.list_workflows(limit=1, cursor="prev_cursor"))

        mock_get.assert_called_once()
        call_kwargs = mock_get.call_args
        assert call_kwargs.kwargs["params"]["limit"] == 1
        assert call_kwargs.kwargs["params"]["cursor"] == "prev_cursor"
        assert result["nextCursor"] == "abc123"

    @patch("agno.tools.n8n.httpx.get")
    def test_get_workflow_success(self, mock_get, n8n_tools):
        mock_get.return_value = httpx.Response(
            status_code=200,
            json={"id": "wf1", "name": "My WF", "active": False, "nodes": []},
            request=httpx.Request("GET", "http://n8n.local:5678/api/v1/workflows/wf1"),
        )

        result = json.loads(n8n_tools.get_workflow("wf1"))

        assert result["id"] == "wf1"
        assert result["name"] == "My WF"

    @patch("agno.tools.n8n.httpx.post")
    def test_activate_workflow_success(self, mock_post, n8n_tools):
        mock_post.return_value = httpx.Response(
            status_code=200,
            json={"id": "wf1", "active": True},
            request=httpx.Request("POST", "http://n8n.local:5678/api/v1/workflows/wf1/activate"),
        )

        result = json.loads(n8n_tools.activate_workflow("wf1"))

        assert result["active"] is True

    @patch("agno.tools.n8n.httpx.post")
    def test_deactivate_workflow_success(self, mock_post, n8n_tools):
        mock_post.return_value = httpx.Response(
            status_code=200,
            json={"id": "wf1", "active": False},
            request=httpx.Request("POST", "http://n8n.local:5678/api/v1/workflows/wf1/deactivate"),
        )

        result = json.loads(n8n_tools.deactivate_workflow("wf1"))

        assert result["active"] is False

    @patch("agno.tools.n8n.httpx.get")
    def test_list_executions_success(self, mock_get, n8n_tools):
        mock_get.return_value = httpx.Response(
            status_code=200,
            json={
                "data": [{"id": "1", "workflowId": "wf1", "status": "success", "finished": True}],
                "nextCursor": None,
            },
            request=httpx.Request("GET", "http://n8n.local:5678/api/v1/executions"),
        )

        result = json.loads(n8n_tools.list_executions(workflow_id="wf1", limit=5))

        call_kwargs = mock_get.call_args
        assert call_kwargs.kwargs["params"]["workflowId"] == "wf1"
        assert call_kwargs.kwargs["params"]["limit"] == 5
        assert result["count"] == 1
        assert result["data"][0]["status"] == "success"

    @patch("agno.tools.n8n.httpx.get")
    def test_get_execution_success(self, mock_get, n8n_tools):
        mock_get.return_value = httpx.Response(
            status_code=200,
            json={"id": "42", "workflowId": "wf1", "status": "success"},
            request=httpx.Request("GET", "http://n8n.local:5678/api/v1/executions/42"),
        )

        result = json.loads(n8n_tools.get_execution("42"))

        assert result["id"] == "42"
        assert result["status"] == "success"

    @patch("agno.tools.n8n.httpx.delete")
    def test_delete_execution_success(self, mock_delete, n8n_tools):
        mock_delete.return_value = httpx.Response(
            status_code=200,
            request=httpx.Request("DELETE", "http://n8n.local:5678/api/v1/executions/42"),
        )

        result = json.loads(n8n_tools.delete_execution("42"))

        assert result["status"] == "deleted"
        assert result["execution_id"] == "42"

    # ---- Error handling tests ----

    @patch("agno.tools.n8n.httpx.get")
    def test_list_workflows_http_error(self, mock_get, n8n_tools):
        response = httpx.Response(
            status_code=401,
            json={"message": "unauthorized"},
            request=httpx.Request("GET", "http://n8n.local:5678/api/v1/workflows"),
        )
        mock_get.return_value = response
        mock_get.return_value.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError("401", request=response.request, response=response)
        )

        result = json.loads(n8n_tools.list_workflows())

        assert "error" in result
        assert "401" in result["error"]

    @patch("agno.tools.n8n.httpx.get")
    def test_list_workflows_connection_error(self, mock_get, n8n_tools):
        mock_get.side_effect = httpx.ConnectError("Connection refused")

        result = json.loads(n8n_tools.list_workflows())

        assert "error" in result
        assert "Connection refused" in result["error"]

    @patch("agno.tools.n8n.httpx.get")
    def test_get_workflow_not_found(self, mock_get, n8n_tools):
        response = httpx.Response(
            status_code=404,
            json={"message": "Not Found"},
            request=httpx.Request("GET", "http://n8n.local:5678/api/v1/workflows/bad-id"),
        )
        mock_get.return_value = response
        mock_get.return_value.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError("404", request=response.request, response=response)
        )

        result = json.loads(n8n_tools.get_workflow("bad-id"))

        assert "error" in result
        assert "404" in result["error"]

    # ---- Async method tests ----

    @pytest.mark.asyncio
    async def test_alist_workflows_success(self):
        tools = N8nTools(base_url="http://n8n.local:5678", api_key="key")
        mock_response = httpx.Response(
            status_code=200,
            json={"data": [{"id": "wf1", "name": "Async WF", "active": True}], "nextCursor": None},
            request=httpx.Request("GET", "http://n8n.local:5678/api/v1/workflows"),
        )
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("agno.tools.n8n.httpx.AsyncClient", return_value=mock_client):
            result = json.loads(await tools.alist_workflows())

        assert result["count"] == 1
        assert result["data"][0]["name"] == "Async WF"

    @pytest.mark.asyncio
    async def test_alist_workflows_active_only(self):
        tools = N8nTools(base_url="http://n8n.local:5678", api_key="key")
        mock_response = httpx.Response(
            status_code=200,
            json={
                "data": [
                    {"id": "wf1", "name": "Active", "active": True},
                    {"id": "wf2", "name": "Inactive", "active": False},
                ],
                "nextCursor": None,
            },
            request=httpx.Request("GET", "http://n8n.local:5678/api/v1/workflows"),
        )
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("agno.tools.n8n.httpx.AsyncClient", return_value=mock_client):
            result = json.loads(await tools.alist_workflows(active_only=True))

        assert result["count"] == 1
        assert result["data"][0]["name"] == "Active"

    @pytest.mark.asyncio
    async def test_aactivate_workflow_success(self):
        tools = N8nTools(base_url="http://n8n.local:5678", api_key="key")
        mock_response = httpx.Response(
            status_code=200,
            json={"id": "wf1", "active": True},
            request=httpx.Request("POST", "http://n8n.local:5678/api/v1/workflows/wf1/activate"),
        )
        mock_client = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("agno.tools.n8n.httpx.AsyncClient", return_value=mock_client):
            result = json.loads(await tools.aactivate_workflow("wf1"))

        assert result["active"] is True

    @pytest.mark.asyncio
    async def test_adelete_execution_success(self):
        tools = N8nTools(base_url="http://n8n.local:5678", api_key="key")
        mock_response = httpx.Response(
            status_code=200,
            request=httpx.Request("DELETE", "http://n8n.local:5678/api/v1/executions/99"),
        )
        mock_client = MagicMock()
        mock_client.delete = AsyncMock(return_value=mock_response)

        with patch("agno.tools.n8n.httpx.AsyncClient", return_value=mock_client):
            result = json.loads(await tools.adelete_execution("99"))

        assert result["status"] == "deleted"
        assert result["execution_id"] == "99"

    @pytest.mark.asyncio
    async def test_alist_workflows_http_error(self):
        tools = N8nTools(base_url="http://n8n.local:5678", api_key="bad-key")
        response = httpx.Response(
            status_code=401,
            json={"message": "unauthorized"},
            request=httpx.Request("GET", "http://n8n.local:5678/api/v1/workflows"),
        )
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=response)
        mock_client.get.return_value.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError("401", request=response.request, response=response)
        )

        with patch("agno.tools.n8n.httpx.AsyncClient", return_value=mock_client):
            result = json.loads(await tools.alist_workflows())

        assert "error" in result
        assert "401" in result["error"]

    @pytest.mark.asyncio
    async def test_alist_workflows_connection_error(self):
        tools = N8nTools(base_url="http://localhost:9999", api_key="key")
        mock_client = MagicMock()
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))

        with patch("agno.tools.n8n.httpx.AsyncClient", return_value=mock_client):
            result = json.loads(await tools.alist_workflows())

        assert "error" in result
        assert "Connection refused" in result["error"]

    @pytest.mark.asyncio
    async def test_aclose_clears_client(self):
        tools = N8nTools(base_url="http://n8n.local:5678", api_key="key")
        mock_client = AsyncMock()
        tools._async_client = mock_client

        await tools.aclose()

        mock_client.aclose.assert_awaited_once()
        assert tools._async_client is None

    @pytest.mark.asyncio
    async def test_aclose_noop_when_no_client(self):
        tools = N8nTools(base_url="http://n8n.local:5678", api_key="key")
        assert tools._async_client is None

        await tools.aclose()

        assert tools._async_client is None
