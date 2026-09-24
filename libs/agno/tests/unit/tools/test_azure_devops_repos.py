"""Unit tests for AzureDevOpsReposTools."""

import json
from unittest.mock import Mock

import pytest

from agno.tools.azure_devops.repos import AzureDevOpsReposTools


@pytest.fixture
def repos_tools():
    tools = AzureDevOpsReposTools(
        organization_url="https://dev.azure.com/org",
        personal_access_token="pat",
        project="MyProject",
    )
    tools._clients["git"] = Mock()
    return tools


def test_init_registers_all_tools():
    tools = AzureDevOpsReposTools(
        organization_url="https://dev.azure.com/org", personal_access_token="pat", project="P"
    )
    names = [func.name for func in tools.functions.values()]
    assert "list_repos" in names
    assert "read_repository_file" in names
    assert "get_repo_file_tree" in names


def test_init_selective_tools():
    tools = AzureDevOpsReposTools(
        organization_url="https://dev.azure.com/org",
        personal_access_token="pat",
        project="P",
        enable_read_repository_file=False,
        enable_get_repo_file_tree=False,
    )
    names = [func.name for func in tools.functions.values()]
    assert "list_repos" in names
    assert "read_repository_file" not in names


def test_async_variants_registered():
    tools = AzureDevOpsReposTools(
        organization_url="https://dev.azure.com/org", personal_access_token="pat", project="P"
    )
    async_names = [func.name for func in tools.async_functions.values()]
    assert "list_repos" in async_names


def test_list_repos_success(repos_tools):
    repo = Mock()
    repo.id = "r1"
    repo.name = "repo-one"
    repo.is_disabled = False
    repos_tools._clients["git"].get_repositories.return_value = [repo]

    result = json.loads(repos_tools.list_repos())
    assert result["repos"][0]["name"] == "repo-one"
    repos_tools._clients["git"].get_repositories.assert_called_once_with(project="MyProject")


def test_read_repository_file_success(repos_tools):
    item = Mock()
    item.content = "# Hello"
    repos_tools._clients["git"].get_item.return_value = item

    result = json.loads(repos_tools.read_repository_file("r1", "/README.md"))
    assert result["content"] == "# Hello"
    assert result["path"] == "/README.md"


def test_get_repo_file_tree_success(repos_tools):
    folder = Mock()
    folder.path = "/src"
    folder.is_folder = True
    file_item = Mock()
    file_item.path = "/src/main.py"
    file_item.is_folder = False
    repos_tools._clients["git"].get_items.return_value = [folder, file_item]

    result = json.loads(repos_tools.get_repo_file_tree("r1"))
    assert "/src - DIR" in result["files"]
    assert "/src/main.py - FILE" in result["files"]


def test_list_repos_error_returns_json(repos_tools):
    repos_tools._clients["git"].get_repositories.side_effect = Exception("boom")
    result = json.loads(repos_tools.list_repos())
    assert result["error"] == "boom"


@pytest.mark.asyncio
async def test_alist_repos_success(repos_tools):
    repo = Mock()
    repo.id = "r1"
    repo.name = "repo-one"
    repo.is_disabled = False
    repos_tools._clients["git"].get_repositories.return_value = [repo]

    result = json.loads(await repos_tools.alist_repos())
    assert result["repos"][0]["name"] == "repo-one"
