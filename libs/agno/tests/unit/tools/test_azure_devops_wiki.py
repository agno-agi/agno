"""Unit tests for AzureDevOpsWikiTools."""

import json
from unittest.mock import Mock

import pytest

from agno.tools.azure_devops.wiki import AzureDevOpsWikiTools


@pytest.fixture
def wiki_tools():
    tools = AzureDevOpsWikiTools(
        organization_url="https://dev.azure.com/org",
        personal_access_token="pat",
        project="MyProject",
    )
    tools._clients["wiki"] = Mock()
    return tools


def test_init_registers_all_tools():
    tools = AzureDevOpsWikiTools(organization_url="https://dev.azure.com/org", personal_access_token="pat", project="P")
    names = [func.name for func in tools.functions.values()]
    assert set(names) == {
        "get_wiki_list",
        "get_wiki_pages",
        "list_wiki_pages",
        "search_in_wiki_pages",
    }


def test_init_selective_tools():
    tools = AzureDevOpsWikiTools(
        organization_url="https://dev.azure.com/org",
        personal_access_token="pat",
        project="P",
        enable_search_in_wiki_pages=False,
    )
    names = [func.name for func in tools.functions.values()]
    assert "search_in_wiki_pages" not in names


def test_get_wiki_list_success(wiki_tools):
    wiki = Mock()
    wiki.id = "w1"
    wiki.name = "Docs"
    wiki.remote_url = "https://example/wiki"
    wiki.mapped_path = "/"
    wiki_tools._clients["wiki"].get_all_wikis.return_value = [wiki]

    result = json.loads(wiki_tools.get_wiki_list())
    assert result["wikis"][0]["name"] == "Docs"
    wiki_tools._clients["wiki"].get_all_wikis.assert_called_once_with(project="MyProject")


def test_get_wiki_pages_success(wiki_tools):
    page = Mock()
    page.id = 1
    page.content = "content"
    page.is_parent_page = False
    page.order = 0
    page.path = "/Home"
    page.remote_url = "https://example/Home"
    page.sub_pages = []
    response = Mock()
    response.page = page
    wiki_tools._clients["wiki"].get_page.return_value = response

    result = json.loads(wiki_tools.get_wiki_pages("Docs", "/Home"))
    assert result["wiki_page"]["path"] == "/Home"


def test_list_wiki_pages_success(wiki_tools):
    page = Mock()
    page.path = "/Home"
    page.url = "https://example/Home"
    page.view_stats = []
    wiki_tools._clients["wiki"].get_pages_batch.return_value = [page]

    result = json.loads(wiki_tools.list_wiki_pages("Docs"))
    assert result["wiki_pages"][0]["path"] == "/Home"


def test_search_in_wiki_pages_matches_content(wiki_tools):
    listed = Mock()
    listed.path = "/Home"
    listed.url = "https://example/Home"
    listed.view_stats = []
    wiki_tools._clients["wiki"].get_pages_batch.return_value = [listed]

    page = Mock()
    page.content = "this mentions agno framework"
    response = Mock()
    response.page = page
    wiki_tools._clients["wiki"].get_page.return_value = response

    result = json.loads(wiki_tools.search_in_wiki_pages("Docs", "agno"))
    assert len(result["results"]) == 1
    assert result["results"][0]["path"] == "/Home"


def test_get_wiki_list_error_returns_json(wiki_tools):
    wiki_tools._clients["wiki"].get_all_wikis.side_effect = Exception("boom")
    result = json.loads(wiki_tools.get_wiki_list())
    assert result["error"] == "boom"


@pytest.mark.asyncio
async def test_aget_wiki_list_success(wiki_tools):
    wiki = Mock()
    wiki.id = "w1"
    wiki.name = "Docs"
    wiki.remote_url = "https://example/wiki"
    wiki.mapped_path = "/"
    wiki_tools._clients["wiki"].get_all_wikis.return_value = [wiki]

    result = json.loads(await wiki_tools.aget_wiki_list())
    assert result["wikis"][0]["name"] == "Docs"
