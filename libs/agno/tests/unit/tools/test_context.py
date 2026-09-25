import json
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from agno.tools.context import ContextTools
from agno.tools.context_client import ContextClient


@pytest.fixture
def context_tools() -> ContextTools:
    tools = ContextTools(api_key="test-key", all=True)
    tools.client = Mock(spec=ContextClient)
    tools.client.aget = AsyncMock()
    tools.client.apost = AsyncMock()
    return tools


def test_default_tools_are_search_and_scrape() -> None:
    tools = ContextTools(api_key="test-key")

    assert set(tools.functions) == {"search_web", "scrape_url"}
    assert set(tools.async_functions) == {"search_web", "scrape_url"}


def test_all_registers_every_supported_tool() -> None:
    tools = ContextTools(api_key="test-key", all=True)
    expected = {
        "search_web",
        "scrape_url",
        "crawl_website",
        "find_website_pages",
        "extract_structured_data",
        "get_brand_profile",
    }

    assert set(tools.functions) == expected
    assert set(tools.async_functions) == expected
    assert all("answer" not in name for name in expected)


def test_search_web_sends_production_request_shape(context_tools: ContextTools) -> None:
    context_tools.client.post.return_value = '{"results": []}'

    result = context_tools.search_web(
        "latest Context.dev updates",
        num_results=20,
        include_domains=["context.dev"],
        exclude_domains=["example.com"],
        freshness="last_week",
        country="us",
        include_markdown=True,
    )

    assert json.loads(result) == {"results": []}
    context_tools.client.post.assert_called_once_with(
        "/web/search",
        {
            "query": "latest Context.dev updates",
            "numResults": 20,
            "includeDomains": ["context.dev"],
            "excludeDomains": ["example.com"],
            "freshness": "last_week",
            "country": "us",
            "markdownOptions": {
                "enabled": True,
                "useMainContentOnly": True,
                "includeLinks": True,
                "includeImages": False,
            },
        },
    )


def test_scrape_url_uses_markdown_endpoint(context_tools: ContextTools) -> None:
    context_tools.client.get.return_value = '{"markdown": "page"}'

    context_tools.scrape_url("https://example.com", max_age_ms=0)

    context_tools.client.get.assert_called_once_with(
        "/web/scrape/markdown",
        {
            "url": "https://example.com",
            "useMainContentOnly": True,
            "includeLinks": True,
            "includeImages": False,
            "maxAgeMs": 0,
        },
    )


def test_crawl_website_omits_unset_optional_fields(context_tools: ContextTools) -> None:
    context_tools.client.post.return_value = '{"results": []}'

    context_tools.crawl_website("https://example.com", max_pages=12)

    context_tools.client.post.assert_called_once_with(
        "/web/crawl",
        {
            "url": "https://example.com",
            "maxPages": 12,
            "followSubdomains": False,
            "useMainContentOnly": True,
            "includeLinks": True,
            "includeImages": False,
        },
    )


def test_find_website_pages_uses_sitemap_query(context_tools: ContextTools) -> None:
    context_tools.client.get.return_value = '{"urls": []}'

    context_tools.find_website_pages(
        "context.dev",
        search="pricing",
        max_links=25,
        sitemap_url="https://context.dev/sitemap.xml",
        url_regex="/docs/.*",
    )

    context_tools.client.get.assert_called_once_with(
        "/web/scrape/sitemap",
        {
            "domain": "context.dev",
            "search": "pricing",
            "maxLinks": 25,
            "sitemapUrl": "https://context.dev/sitemap.xml",
            "urlRegex": "/docs/.*",
        },
    )


def test_extract_structured_data_preserves_false_values(context_tools: ContextTools) -> None:
    context_tools.client.post.return_value = '{"data": {}}'
    schema = {"type": "object", "properties": {"price": {"type": "string"}}}

    context_tools.extract_structured_data(
        "https://context.dev/pricing",
        schema,
        instructions="Return displayed prices",
        max_pages=3,
        max_depth=0,
    )

    context_tools.client.post.assert_called_once_with(
        "/web/extract",
        {
            "url": "https://context.dev/pricing",
            "schema": schema,
            "instructions": "Return displayed prices",
            "maxPages": 3,
            "maxDepth": 0,
            "followSubdomains": False,
            "factCheck": False,
        },
    )


def test_get_brand_profile_uses_typed_domain_lookup(context_tools: ContextTools) -> None:
    context_tools.client.post.return_value = '{"domain": "stripe.com"}'

    context_tools.get_brand_profile("stripe.com", maximum_speed=True)

    context_tools.client.post.assert_called_once_with(
        "/brand/retrieve",
        {
            "type": "by_domain",
            "domain": "stripe.com",
            "maxSpeed": True,
            "maxAgeMs": 7776000000,
        },
    )


@pytest.mark.asyncio
async def test_async_tool_uses_async_client(context_tools: ContextTools) -> None:
    context_tools.client.apost.return_value = '{"results": []}'

    result = await context_tools.asearch_web("Context.dev")

    assert json.loads(result) == {"results": []}
    context_tools.client.apost.assert_awaited_once()
    context_tools.client.post.assert_not_called()


def test_client_sends_bearer_auth_and_serializes_success() -> None:
    response = httpx.Response(
        200,
        json={"results": [{"url": "https://example.com"}]},
        request=httpx.Request("POST", "https://api.context.dev/v1/web/search"),
    )
    client = ContextClient("test-key", "https://api.context.dev/v1/", 30)

    with patch("agno.tools.context_client.httpx.post", return_value=response) as request:
        result = client.post("/web/search", {"query": "test"})

    assert json.loads(result)["results"][0]["url"] == "https://example.com"
    assert request.call_args.kwargs["headers"]["Authorization"] == "Bearer test-key"
    assert request.call_args.args[0] == "https://api.context.dev/v1/web/search"


def test_client_returns_structured_api_error() -> None:
    response = httpx.Response(
        400,
        json={"message": "Invalid query", "error_code": "INPUT_VALIDATION_ERROR"},
        request=httpx.Request("POST", "https://api.context.dev/v1/web/search"),
    )
    client = ContextClient("test-key", "https://api.context.dev/v1", 30)

    with patch("agno.tools.context_client.httpx.post", return_value=response):
        result = json.loads(client.post("/web/search", {"query": ""}))

    assert result == {
        "error": "Context.dev API request failed",
        "status_code": 400,
        "details": {"message": "Invalid query", "error_code": "INPUT_VALIDATION_ERROR"},
    }


def test_client_requires_api_key_before_request() -> None:
    client = ContextClient(None, "https://api.context.dev/v1", 30)

    with pytest.raises(ValueError, match="CONTEXT_API_KEY"):
        client.get("/web/scrape/markdown", {"url": "https://example.com"})
