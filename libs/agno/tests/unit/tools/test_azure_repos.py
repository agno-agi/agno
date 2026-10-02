import json
import os
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from agno.tools.azure_repos import AzureReposTools


def _build_tools(**overrides: Any) -> AzureReposTools:
    defaults: Dict[str, Any] = {
        "organization_url": "https://dev.azure.com/myorg",
        "personal_access_token": "test_token",
        "project": "MyProject",
    }
    defaults.update(overrides)
    return AzureReposTools(**defaults)


class TestAzureReposToolsInit:
    def test_init_explicit_args(self):
        tools = _build_tools()
        assert tools.organization_url == "https://dev.azure.com/myorg"
        assert tools.personal_access_token == "test_token"
        assert tools.project == "MyProject"
        assert tools.api_version == "7.1"

    def test_init_strips_trailing_slash(self):
        tools = _build_tools(organization_url="https://dev.azure.com/myorg/")
        assert tools.organization_url == "https://dev.azure.com/myorg"

    def test_init_uses_environment_variables(self):
        with patch.dict(
            os.environ,
            {
                "AZURE_DEVOPS_ORG_URL": "https://dev.azure.com/envorg",
                "AZURE_DEVOPS_PAT": "env_token",
                "AZURE_DEVOPS_PROJECT": "EnvProject",
            },
            clear=True,
        ):
            tools = AzureReposTools()
        assert tools.organization_url == "https://dev.azure.com/envorg"
        assert tools.personal_access_token == "env_token"
        assert tools.project == "EnvProject"

    def test_init_missing_org_url_raises(self):
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError, match="organization URL"):
                AzureReposTools(personal_access_token="token")

    def test_init_missing_pat_raises(self):
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError, match="personal access token"):
                AzureReposTools(organization_url="https://dev.azure.com/myorg")


class TestToolRegistration:
    def test_default_flags_register_expected_tools(self):
        tools = _build_tools()
        function_names = set(tools.functions.keys())
        async_function_names = set(tools.async_functions.keys())

        # Default ON read + write
        for name in [
            "list_repositories",
            "get_repository",
            "list_branches",
            "list_pull_requests",
            "get_pull_request",
            "get_pull_request_commits",
            "list_pull_request_threads",
            "list_commits",
            "get_file_content",
            "list_items",
            "create_repository",
            "create_branch",
            "create_pull_request",
            "create_pull_request_comment",
        ]:
            assert name in function_names
            assert name in async_function_names

        # Default OFF destructive
        assert "delete_repository" not in function_names
        assert "delete_branch" not in function_names

    def test_async_tools_registered_with_sync_names(self):
        tools = _build_tools()
        assert "alist_repositories" not in tools.async_functions
        assert "list_repositories" in tools.async_functions

    def test_destructive_flags_enable_when_requested(self):
        tools = _build_tools(enable_delete_repository=True, enable_delete_branch=True)
        assert "delete_repository" in tools.functions
        assert "delete_branch" in tools.functions
        assert "delete_repository" in tools.async_functions
        assert "delete_branch" in tools.async_functions

    def test_enable_flags_select_subset(self):
        tools = _build_tools(
            enable_list_repositories=True,
            enable_get_repository=False,
            enable_list_branches=False,
            enable_list_pull_requests=False,
            enable_get_pull_request=False,
            enable_get_pull_request_commits=False,
            enable_list_pull_request_threads=False,
            enable_list_commits=False,
            enable_get_file_content=False,
            enable_list_items=False,
            enable_create_repository=False,
            enable_create_branch=False,
            enable_create_pull_request=False,
            enable_create_pull_request_comment=False,
        )
        assert set(tools.functions.keys()) == {"list_repositories"}
        assert set(tools.async_functions.keys()) == {"list_repositories"}


class TestHelpers:
    def test_build_url_with_project(self):
        tools = _build_tools()
        assert (
            tools._build_url("/git/repositories", project="OtherProject")
            == "https://dev.azure.com/myorg/OtherProject/_apis/git/repositories"
        )

    def test_build_url_uses_default_project(self):
        tools = _build_tools()
        assert tools._build_url("/git/repositories") == "https://dev.azure.com/myorg/MyProject/_apis/git/repositories"

    def test_build_url_without_project(self):
        tools = _build_tools(project=None)
        with patch.dict(os.environ, {}, clear=True):
            tools.project = None
            assert tools._build_url("/git/pullrequests") == "https://dev.azure.com/myorg/_apis/git/pullrequests"

    def test_build_headers_contains_basic_auth(self):
        tools = _build_tools()
        headers = tools._build_headers(content_type="application/json")
        assert headers["Authorization"].startswith("Basic ")
        assert headers["Accept"] == "application/json"
        assert headers["Content-Type"] == "application/json"

    def test_params_with_version_drops_none_and_serializes_bool(self):
        tools = _build_tools()
        params = tools._params_with_version({"a": "x", "b": None, "c": True, "d": False})
        assert params == {"api-version": "7.1", "a": "x", "c": "true", "d": "false"}


class TestSyncOperations:
    def _patch_request(self, tools, return_value):
        return patch.object(tools, "_request", return_value=return_value)

    def test_list_repositories_success(self):
        tools = _build_tools()
        payload = {
            "value": [
                {
                    "id": "abc",
                    "name": "demo",
                    "url": "https://dev.azure.com/myorg/_apis/git/repositories/abc",
                    "webUrl": "https://dev.azure.com/myorg/_git/demo",
                    "defaultBranch": "refs/heads/main",
                    "size": 1024,
                    "isDisabled": False,
                    "project": {"id": "p1", "name": "MyProject"},
                }
            ]
        }
        with self._patch_request(tools, payload):
            result = tools.list_repositories()
        data = json.loads(result)
        assert len(data["data"]) == 1
        assert data["data"][0]["name"] == "demo"
        assert data["data"][0]["project"]["name"] == "MyProject"
        assert data["meta"]["returned_items"] == 1

    def test_get_repository_success(self):
        tools = _build_tools()
        repo_payload = {
            "id": "abc",
            "name": "demo",
            "defaultBranch": "refs/heads/main",
            "project": {"id": "p1", "name": "MyProject"},
        }
        with self._patch_request(tools, repo_payload) as mock_request:
            result = tools.get_repository("demo")
        data = json.loads(result)
        assert data["id"] == "abc"
        assert data["name"] == "demo"
        mock_request.assert_called_once_with("GET", "/git/repositories/demo", project=None)

    def test_list_pull_requests_builds_correct_params(self):
        tools = _build_tools()
        payload: Dict[str, Any] = {"value": []}
        with self._patch_request(tools, payload) as mock_request:
            tools.list_pull_requests(
                "demo",
                status="completed",
                source_branch="feature",
                target_branch="main",
                page=2,
                per_page=10,
            )
        _, kwargs = mock_request.call_args
        params = kwargs["params"]
        assert params["searchCriteria.status"] == "completed"
        assert params["searchCriteria.sourceRefName"] == "refs/heads/feature"
        assert params["searchCriteria.targetRefName"] == "refs/heads/main"
        assert params["$top"] == 10
        assert params["$skip"] == 10

    def test_create_pull_request_success(self):
        tools = _build_tools()
        pr_payload = {
            "pullRequestId": 42,
            "title": "Add feature",
            "status": "active",
            "sourceRefName": "refs/heads/feature",
            "targetRefName": "refs/heads/main",
            "createdBy": {"displayName": "Author"},
            "repository": {"id": "abc", "name": "demo"},
        }
        with self._patch_request(tools, pr_payload) as mock_request:
            result = tools.create_pull_request(
                "demo",
                source_branch="feature",
                target_branch="main",
                title="Add feature",
                description="desc",
            )
        data = json.loads(result)
        assert data["id"] == 42
        assert data["title"] == "Add feature"
        _, kwargs = mock_request.call_args
        body = kwargs["json_body"]
        assert body["sourceRefName"] == "refs/heads/feature"
        assert body["targetRefName"] == "refs/heads/main"
        assert body["isDraft"] is False

    def test_create_branch_uses_default_branch_when_source_missing(self):
        tools = _build_tools()
        repo_payload = {"defaultBranch": "refs/heads/main"}
        ref_payload = {"value": [{"objectId": "deadbeef"}]}
        post_payload = {"value": [{"name": "refs/heads/feature", "newObjectId": "deadbeef", "success": True}]}

        def fake_request(method, path, project=None, params=None, json_body=None, return_text=False):
            if method == "GET" and path.endswith("/refs"):
                return ref_payload
            if method == "GET":
                return repo_payload
            if method == "POST":
                return post_payload
            raise AssertionError(f"unexpected call {method} {path}")

        with patch.object(tools, "_request", side_effect=fake_request):
            result = tools.create_branch("demo", "feature")
        data = json.loads(result)
        assert data["name"] == "refs/heads/feature"
        assert data["object_id"] == "deadbeef"

    def test_delete_repository_success(self):
        tools = _build_tools(enable_delete_repository=True)
        with self._patch_request(tools, None) as mock_request:
            result = tools.delete_repository("demo")
        data = json.loads(result)
        assert "deleted" in data["message"]
        mock_request.assert_called_once_with("DELETE", "/git/repositories/demo", project=None)

    def test_http_error_returns_json_error(self):
        tools = _build_tools()
        request = httpx.Request("GET", "https://dev.azure.com/myorg/_apis/git/repositories")
        response = httpx.Response(404, json={"message": "Not found"}, request=request)
        error = httpx.HTTPStatusError("not found", request=request, response=response)
        with patch.object(tools, "_request", side_effect=error):
            result = tools.list_repositories()
        data = json.loads(result)
        assert data["error"] == "404: Not found"

    def test_get_file_content_success(self):
        tools = _build_tools()
        payload = {"content": "hello world"}
        with self._patch_request(tools, payload) as mock_request:
            result = tools.get_file_content("demo", "/README.md", branch="main")
        data = json.loads(result)
        assert data["content"] == "hello world"
        assert data["path"] == "/README.md"
        _, kwargs = mock_request.call_args
        assert kwargs["params"]["versionDescriptor.version"] == "main"


class TestAsyncOperations:
    @pytest.mark.asyncio
    async def test_alist_repositories_success(self):
        tools = _build_tools()
        payload = {"value": [{"id": "abc", "name": "demo", "project": {"id": "p1", "name": "MyProject"}}]}
        with patch.object(tools, "_arequest", AsyncMock(return_value=payload)):
            result = await tools.alist_repositories()
        data = json.loads(result)
        assert data["data"][0]["name"] == "demo"

    @pytest.mark.asyncio
    async def test_aget_pull_request_success(self):
        tools = _build_tools()
        payload = {
            "pullRequestId": 7,
            "title": "Fix bug",
            "status": "active",
            "createdBy": {"displayName": "Dev"},
            "repository": {"id": "abc", "name": "demo"},
        }
        with patch.object(tools, "_arequest", AsyncMock(return_value=payload)) as mock_request:
            result = await tools.aget_pull_request(7)
        data = json.loads(result)
        assert data["id"] == 7
        mock_request.assert_awaited_once_with("GET", "/git/pullrequests/7", project=None)

    @pytest.mark.asyncio
    async def test_acreate_pull_request_comment_success(self):
        tools = _build_tools()
        payload = {
            "id": 1,
            "status": "active",
            "comments": [{"id": 11, "content": "LGTM", "author": {"displayName": "Dev"}}],
        }
        with patch.object(tools, "_arequest", AsyncMock(return_value=payload)) as mock_request:
            result = await tools.acreate_pull_request_comment("demo", 7, "LGTM")
        data = json.loads(result)
        assert data["id"] == 1
        assert data["comments"][0]["content"] == "LGTM"
        _, kwargs = mock_request.call_args
        assert kwargs["json_body"]["comments"][0]["content"] == "LGTM"

    @pytest.mark.asyncio
    async def test_alist_pull_requests_http_error(self):
        tools = _build_tools()
        request = httpx.Request("GET", "https://dev.azure.com/myorg/MyProject/_apis/git/repositories/demo/pullrequests")
        response = httpx.Response(403, json={"message": "Forbidden"}, request=request)
        error = httpx.HTTPStatusError("forbidden", request=request, response=response)
        with patch.object(tools, "_arequest", AsyncMock(side_effect=error)):
            result = await tools.alist_pull_requests("demo")
        data = json.loads(result)
        assert data["error"] == "403: Forbidden"

    @pytest.mark.asyncio
    async def test_aclose_releases_async_client(self):
        tools = _build_tools()
        mock_client = MagicMock()
        mock_client.aclose = AsyncMock()
        tools._async_client = mock_client
        await tools.aclose()
        mock_client.aclose.assert_awaited_once()
        assert tools._async_client is None
