import json
import os
from unittest.mock import AsyncMock, MagicMock, call, patch

import httpx
import pytest
from gitlab.exceptions import GitlabError

from agno.tools.gitlab import GitlabTools


class TestGitlabTools:
    @pytest.fixture
    def gitlab_tools(self):
        with patch("agno.tools.gitlab.gitlab.Gitlab") as mock_gitlab:
            mock_client = MagicMock()
            mock_gitlab.return_value = mock_client
            tools = GitlabTools(access_token="test_token")
            yield tools, mock_client

    def test_init_with_explicit_token(self):
        with patch("agno.tools.gitlab.gitlab.Gitlab") as mock_gitlab:
            GitlabTools(access_token="explicit_token", base_url="https://gitlab.example.com", timeout=60)

            mock_gitlab.assert_called_once_with(
                url="https://gitlab.example.com", timeout=60, private_token="explicit_token"
            )

    def test_init_uses_environment_variables(self):
        with (
            patch("agno.tools.gitlab.gitlab.Gitlab") as mock_gitlab,
            patch.dict(
                os.environ,
                {
                    "GITLAB_ACCESS_TOKEN": "env_token",
                    "GITLAB_BASE_URL": "https://gitlab.example.com",
                },
            ),
        ):
            GitlabTools()
            mock_gitlab.assert_called_once_with(url="https://gitlab.example.com", timeout=30, private_token="env_token")

    def test_init_without_token(self):
        with (
            patch("agno.tools.gitlab.gitlab.Gitlab") as mock_gitlab,
            patch.dict(os.environ, {}, clear=True),
        ):
            GitlabTools()
            mock_gitlab.assert_called_once_with(url="https://gitlab.com", timeout=30)

    def test_init_failure_raises_value_error(self):
        with patch("agno.tools.gitlab.gitlab.Gitlab", side_effect=Exception("bad config")):
            with pytest.raises(ValueError, match="Failed to initialize GitLab client"):
                GitlabTools(access_token="token")

    @pytest.mark.asyncio
    async def test_aget_uses_internal_async_client(self):
        response_one = httpx.Response(
            status_code=200,
            json={"ok": True},
            request=httpx.Request("GET", "https://gitlab.com/api/v4/projects"),
        )
        response_two = httpx.Response(
            status_code=200,
            json={"ok": "again"},
            request=httpx.Request("GET", "https://gitlab.com/api/v4/projects"),
        )
        mock_async_client = MagicMock()
        mock_async_client.get = AsyncMock(side_effect=[response_one, response_two])

        with patch("agno.tools.gitlab.gitlab.Gitlab") as mock_gitlab:
            mock_gitlab.return_value = MagicMock()
            tools = GitlabTools(access_token="token")

        with patch("agno.tools.gitlab.httpx.AsyncClient", return_value=mock_async_client) as mock_async_client_factory:
            first_payload = await tools._aget("/projects", params={"page": 1})
            second_payload = await tools._aget("/projects", params={"page": 2})

        mock_async_client_factory.assert_called_once_with(timeout=30)
        mock_async_client.get.assert_has_awaits(
            [
                call("https://gitlab.com/api/v4/projects", params={"page": 1}, headers={"PRIVATE-TOKEN": "token"}),
                call("https://gitlab.com/api/v4/projects", params={"page": 2}, headers={"PRIVATE-TOKEN": "token"}),
            ]
        )
        assert first_payload == {"ok": True}
        assert second_payload == {"ok": "again"}

    def test_async_tools_registered_with_sync_names(self):
        with patch("agno.tools.gitlab.gitlab.Gitlab") as mock_gitlab:
            mock_gitlab.return_value = MagicMock()
            tools = GitlabTools(access_token="token")

        assert "list_projects" in tools.async_functions
        assert "get_project" in tools.async_functions
        assert "list_merge_requests" in tools.async_functions
        assert "get_merge_request" in tools.async_functions
        assert "list_issues" in tools.async_functions
        assert "alist_projects" not in tools.async_functions

    def test_enable_flags_register_selected_tools_only(self):
        with patch("agno.tools.gitlab.gitlab.Gitlab") as mock_gitlab:
            mock_gitlab.return_value = MagicMock()
            tools = GitlabTools(
                enable_list_projects=True,
                enable_get_projects=False,
                enable_list_merge_requests=False,
                enable_get_merge_request=True,
                enable_list_issues=False,
            )

        assert set(tools.functions.keys()) == {"list_projects", "get_merge_request"}
        assert set(tools.async_functions.keys()) == {"list_projects", "get_merge_request"}

    def test_list_projects_success(self, gitlab_tools):
        tools, mock_client = gitlab_tools

        project = MagicMock()
        project.id = 1
        project.name = "Agno"
        project.path = "agno"
        project.path_with_namespace = "agno-agi/agno"
        project.description = "Repository"
        project.web_url = "https://gitlab.com/agno-agi/agno"
        project.default_branch = "main"
        project.visibility = "public"
        project.archived = False
        project.last_activity_at = "2026-02-25T00:00:00Z"
        mock_client.projects.list.return_value = [project]

        result = tools.list_projects(search="agno", page=2, per_page=150, owned=True)
        result_data = json.loads(result)

        mock_client.projects.list.assert_called_once_with(
            page=2, per_page=100, owned=True, membership=False, search="agno"
        )
        assert len(result_data["data"]) == 1
        assert result_data["data"][0]["path_with_namespace"] == "agno-agi/agno"
        assert result_data["meta"]["per_page"] == 100
        assert result_data["meta"]["current_page"] == 2

    def test_get_project_success(self, gitlab_tools):
        tools, mock_client = gitlab_tools

        project = MagicMock()
        project.id = 10
        project.name = "demo"
        project.path = "demo"
        project.path_with_namespace = "team/demo"
        project.description = "Demo project"
        project.web_url = "https://gitlab.com/team/demo"
        project.default_branch = "main"
        project.visibility = "private"
        project.archived = False
        project.last_activity_at = "2026-02-24T00:00:00Z"
        mock_client.projects.get.return_value = project

        result = tools.get_project("team/demo")
        result_data = json.loads(result)

        mock_client.projects.get.assert_called_once_with("team/demo")
        assert result_data["id"] == 10
        assert result_data["visibility"] == "private"

    def test_list_merge_requests_success(self, gitlab_tools):
        tools, mock_client = gitlab_tools

        project = MagicMock()
        mr = MagicMock()
        mr.id = 2
        mr.iid = 42
        mr.title = "Add feature"
        mr.description = "Feature details"
        mr.state = "opened"
        mr.web_url = "https://gitlab.com/team/demo/-/merge_requests/42"
        mr.source_branch = "feature-branch"
        mr.target_branch = "main"
        mr.author = {"username": "dev-user"}
        mr.created_at = "2026-02-25T00:00:00Z"
        mr.updated_at = "2026-02-25T01:00:00Z"
        mr.merged_at = None
        project.mergerequests.list.return_value = [mr]
        mock_client.projects.get.return_value = project

        result = tools.list_merge_requests(
            "team/demo", state="all", source_branch="feature-branch", target_branch="main", author_username="dev-user"
        )
        result_data = json.loads(result)

        mock_client.projects.get.assert_called_once_with("team/demo")
        project.mergerequests.list.assert_called_once_with(
            state="all",
            page=1,
            per_page=20,
            source_branch="feature-branch",
            target_branch="main",
            author_username="dev-user",
        )
        assert result_data["data"][0]["iid"] == 42
        assert result_data["data"][0]["author"] == "dev-user"

    def test_get_merge_request_success(self, gitlab_tools):
        tools, mock_client = gitlab_tools

        project = MagicMock()
        mr = MagicMock()
        mr.id = 6
        mr.iid = 12
        mr.title = "Fix tests"
        mr.description = "Fix CI tests"
        mr.state = "merged"
        mr.web_url = "https://gitlab.com/team/demo/-/merge_requests/12"
        mr.source_branch = "fix/tests"
        mr.target_branch = "main"
        mr.author = {"username": "maintainer"}
        mr.created_at = "2026-02-24T10:00:00Z"
        mr.updated_at = "2026-02-24T10:15:00Z"
        mr.merged_at = "2026-02-24T10:20:00Z"
        project.mergerequests.get.return_value = mr
        mock_client.projects.get.return_value = project

        result = tools.get_merge_request("team/demo", 12)
        result_data = json.loads(result)

        mock_client.projects.get.assert_called_once_with("team/demo")
        project.mergerequests.get.assert_called_once_with(12)
        assert result_data["state"] == "merged"
        assert result_data["iid"] == 12

    def test_list_issues_success(self, gitlab_tools):
        tools, mock_client = gitlab_tools

        project = MagicMock()
        issue = MagicMock()
        issue.id = 11
        issue.iid = 7
        issue.title = "Bug: parser edge case"
        issue.description = "Handle invalid payloads"
        issue.state = "opened"
        issue.labels = ["bug", "backend"]
        issue.web_url = "https://gitlab.com/team/demo/-/issues/7"
        issue.author = {"username": "reporter"}
        issue.assignees = [{"username": "developer"}]
        issue.created_at = "2026-02-23T11:00:00Z"
        issue.updated_at = "2026-02-23T12:00:00Z"
        issue.due_date = None
        project.issues.list.return_value = [issue]
        mock_client.projects.get.return_value = project

        result = tools.list_issues("team/demo", labels="bug,backend", assignee_username="developer", search="parser")
        result_data = json.loads(result)

        project.issues.list.assert_called_once_with(
            state="opened",
            page=1,
            per_page=20,
            labels="bug,backend",
            assignee_username="developer",
            search="parser",
        )
        assert result_data["data"][0]["iid"] == 7
        assert result_data["data"][0]["assignees"] == ["developer"]

    def test_list_projects_gitlab_error(self, gitlab_tools):
        tools, mock_client = gitlab_tools
        mock_client.projects.list.side_effect = GitlabError("API failure")

        result = tools.list_projects()
        result_data = json.loads(result)

        assert "error" in result_data
        assert "API failure" in result_data["error"]

    @pytest.mark.asyncio
    async def test_alist_projects_success(self):
        projects_payload = [
            {
                "id": 1,
                "name": "Agno",
                "path": "agno",
                "path_with_namespace": "agno-agi/agno",
                "description": "Repository",
                "web_url": "https://gitlab.com/agno-agi/agno",
                "default_branch": "main",
                "visibility": "public",
                "archived": False,
                "last_activity_at": "2026-02-25T00:00:00Z",
            }
        ]

        with patch("agno.tools.gitlab.gitlab.Gitlab") as mock_gitlab:
            mock_gitlab.return_value = MagicMock()
            tools = GitlabTools(access_token="test_token")

        aget_mock = AsyncMock(return_value=projects_payload)
        with patch.object(tools, "_aget", aget_mock):
            result = await tools.alist_projects(search="agno", page=2, per_page=150, owned=True)

        result_data = json.loads(result)

        aget_mock.assert_awaited_once_with(
            "/projects",
            params={"page": 2, "per_page": 100, "owned": True, "membership": False, "search": "agno"},
        )
        assert result_data["data"][0]["path_with_namespace"] == "agno-agi/agno"
        assert result_data["meta"]["per_page"] == 100

    @pytest.mark.asyncio
    async def test_aget_project_success(self):
        project_payload = {
            "id": 10,
            "name": "demo",
            "path": "demo",
            "path_with_namespace": "team/demo",
            "description": "Demo project",
            "web_url": "https://gitlab.com/team/demo",
            "default_branch": "main",
            "visibility": "private",
            "archived": False,
            "last_activity_at": "2026-02-24T00:00:00Z",
        }

        with patch("agno.tools.gitlab.gitlab.Gitlab") as mock_gitlab:
            mock_gitlab.return_value = MagicMock()
            tools = GitlabTools()

        aget_mock = AsyncMock(return_value=project_payload)
        with patch.object(tools, "_aget", aget_mock):
            result = await tools.aget_project("team/demo")

        result_data = json.loads(result)

        aget_mock.assert_awaited_once_with("/projects/team%2Fdemo")
        assert result_data["visibility"] == "private"

    @pytest.mark.asyncio
    async def test_alist_merge_requests_success(self):
        merge_requests_payload = [
            {
                "id": 2,
                "iid": 42,
                "title": "Add feature",
                "description": "Feature details",
                "state": "opened",
                "web_url": "https://gitlab.com/team/demo/-/merge_requests/42",
                "source_branch": "feature-branch",
                "target_branch": "main",
                "author": {"username": "dev-user"},
                "created_at": "2026-02-25T00:00:00Z",
                "updated_at": "2026-02-25T01:00:00Z",
                "merged_at": None,
            }
        ]

        with patch("agno.tools.gitlab.gitlab.Gitlab") as mock_gitlab:
            mock_gitlab.return_value = MagicMock()
            tools = GitlabTools()

        aget_mock = AsyncMock(return_value=merge_requests_payload)
        with patch.object(tools, "_aget", aget_mock):
            result = await tools.alist_merge_requests(
                "team/demo",
                state="all",
                source_branch="feature-branch",
                target_branch="main",
                author_username="dev-user",
            )

        result_data = json.loads(result)

        aget_mock.assert_awaited_once_with(
            "/projects/team%2Fdemo/merge_requests",
            params={
                "state": "all",
                "page": 1,
                "per_page": 20,
                "source_branch": "feature-branch",
                "target_branch": "main",
                "author_username": "dev-user",
            },
        )
        assert result_data["data"][0]["iid"] == 42
        assert result_data["data"][0]["author"] == "dev-user"

    @pytest.mark.asyncio
    async def test_alist_issues_success(self):
        issues_payload = [
            {
                "id": 11,
                "iid": 7,
                "title": "Bug: parser edge case",
                "description": "Handle invalid payloads",
                "state": "opened",
                "labels": ["bug", "backend"],
                "web_url": "https://gitlab.com/team/demo/-/issues/7",
                "author": {"username": "reporter"},
                "assignees": [{"username": "developer"}],
                "created_at": "2026-02-23T11:00:00Z",
                "updated_at": "2026-02-23T12:00:00Z",
                "due_date": None,
            }
        ]

        with patch("agno.tools.gitlab.gitlab.Gitlab") as mock_gitlab:
            mock_gitlab.return_value = MagicMock()
            tools = GitlabTools()

        aget_mock = AsyncMock(return_value=issues_payload)
        with patch.object(tools, "_aget", aget_mock):
            result = await tools.alist_issues(
                "team/demo", labels="bug,backend", assignee_username="developer", search="parser"
            )

        result_data = json.loads(result)

        aget_mock.assert_awaited_once_with(
            "/projects/team%2Fdemo/issues",
            params={
                "state": "opened",
                "page": 1,
                "per_page": 20,
                "labels": "bug,backend",
                "assignee_username": "developer",
                "search": "parser",
            },
        )
        assert result_data["data"][0]["iid"] == 7
        assert result_data["data"][0]["assignees"] == ["developer"]

    @pytest.mark.asyncio
    async def test_aget_project_http_error(self):
        response = httpx.Response(
            status_code=404,
            json={"message": "404 Project Not Found"},
            request=httpx.Request("GET", "https://gitlab.com/api/v4/projects/missing%2Fproject"),
        )
        with patch("agno.tools.gitlab.gitlab.Gitlab") as mock_gitlab:
            mock_gitlab.return_value = MagicMock()
            tools = GitlabTools()

        error = httpx.HTTPStatusError("404 Project Not Found", request=response.request, response=response)
        with patch.object(tools, "_aget", AsyncMock(side_effect=error)):
            result = await tools.aget_project("missing/project")
        result_data = json.loads(result)

        assert result_data["error"] == "404: 404 Project Not Found"
