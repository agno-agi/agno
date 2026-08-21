"""Unit tests for XquikTools."""

import inspect
import json
from collections.abc import Callable
from typing import Any, Dict, List, Optional

import httpx
import pytest

from agno.tools.xquik import XquikTools

_SYNC_CLIENT = httpx.Client
_ASYNC_CLIENT = httpx.AsyncClient


@pytest.fixture
def xquik_tools() -> XquikTools:
    return XquikTools(api_key="xq_test_key")


def _response(request: httpx.Request, data: Any, status_code: int = 200) -> httpx.Response:
    return httpx.Response(status_code, json=data, request=request)


def _install_transport(
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[[httpx.Request], httpx.Response],
) -> List[httpx.Request]:
    requests: List[httpx.Request] = []

    def capture(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    transport = httpx.MockTransport(capture)
    monkeypatch.setattr(
        "agno.tools.xquik.httpx.Client",
        lambda **kwargs: _SYNC_CLIENT(transport=transport, **kwargs),
    )
    monkeypatch.setattr(
        "agno.tools.xquik.httpx.AsyncClient",
        lambda **kwargs: _ASYNC_CLIENT(transport=transport, **kwargs),
    )
    return requests


def _tweet(author: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {
        "id": "123456",
        "text": "Hello world",
        "createdAt": "2026-04-10T12:00:00Z",
        "author": author
        if author is not None
        else {"id": "789", "name": "Test User", "username": "testuser", "verified": True},
        "likeCount": 42,
        "retweetCount": 5,
        "replyCount": 3,
        "quoteCount": 1,
        "viewCount": 1000,
        "bookmarkCount": 2,
    }


def test_init_registers_matching_sync_and_async_tools() -> None:
    tools = XquikTools(api_key="xq_test_key")

    expected = {"search_posts", "get_user_info", "get_tweet", "get_user_posts", "get_trends"}
    assert set(tools.get_functions()) == expected
    assert set(tools.get_async_functions()) == expected
    assert all(inspect.iscoroutinefunction(function.entrypoint) for function in tools.get_async_functions().values())


def test_init_respects_tool_flags() -> None:
    tools = XquikTools(
        api_key="xq_test_key",
        enable_search_posts=True,
        enable_get_user_info=False,
        enable_get_tweet=False,
        enable_get_user_posts=False,
        enable_get_trends=False,
    )

    assert set(tools.get_functions()) == {"search_posts"}
    assert set(tools.get_async_functions()) == {"search_posts"}


def test_all_overrides_disabled_tool_flags() -> None:
    tools = XquikTools(
        api_key="xq_test_key",
        enable_search_posts=False,
        enable_get_user_info=False,
        enable_get_tweet=False,
        enable_get_user_posts=False,
        enable_get_trends=False,
        all=True,
    )

    assert len(tools.get_functions()) == 5
    assert len(tools.get_async_functions()) == 5


def test_search_posts_formats_results_and_preserves_cursor(
    xquik_tools: XquikTools, monkeypatch: pytest.MonkeyPatch
) -> None:
    requests = _install_transport(
        monkeypatch,
        lambda request: _response(
            request,
            {"tweets": [_tweet()], "has_next_page": True, "next_cursor": "cursor-2"},
        ),
    )

    result = json.loads(xquik_tools.search_posts("advanced Twitter search", cursor="cursor-1"))

    assert result == {
        "query": "advanced Twitter search",
        "count": 1,
        "posts": [
            {
                "id": "123456",
                "text": "Hello world",
                "created_at": "2026-04-10T12:00:00Z",
                "author": {
                    "id": "789",
                    "name": "Test User",
                    "username": "testuser",
                    "verified": True,
                },
                "url": "https://x.com/testuser/status/123456",
                "metrics": {
                    "like_count": 42,
                    "retweet_count": 5,
                    "reply_count": 3,
                    "quote_count": 1,
                    "view_count": 1000,
                    "bookmark_count": 2,
                },
            }
        ],
        "has_next_page": True,
        "next_cursor": "cursor-2",
    }
    assert requests[0].url.path == "/api/v1/x/tweets/search"
    assert requests[0].url.params["q"] == "advanced Twitter search"
    assert requests[0].url.params["cursor"] == "cursor-1"
    assert requests[0].headers["x-api-key"] == "xq_test_key"


@pytest.mark.asyncio
async def test_async_search_posts_uses_the_same_contract(
    xquik_tools: XquikTools, monkeypatch: pytest.MonkeyPatch
) -> None:
    requests = _install_transport(
        monkeypatch,
        lambda request: _response(request, {"tweets": [], "has_next_page": False, "next_cursor": ""}),
    )

    result = json.loads(await xquik_tools.asearch_posts("agents"))

    assert result["posts"] == []
    assert requests[0].url.params["queryType"] == "Top"


def test_search_posts_caps_agent_output_and_rejects_invalid_input(
    xquik_tools: XquikTools, monkeypatch: pytest.MonkeyPatch
) -> None:
    requests = _install_transport(monkeypatch, lambda request: _response(request, {"tweets": []}))

    xquik_tools.search_posts("agents", max_results=500)

    assert requests[0].url.params["limit"] == "200"
    assert json.loads(xquik_tools.search_posts(""))["error"] == "Please provide a query to search for."
    assert "greater than 0" in json.loads(xquik_tools.search_posts("agents", max_results=0))["error"]
    assert len(requests) == 1


def test_search_posts_retains_tweets_with_nullable_authors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tools = XquikTools(api_key="xq_test_key", include_post_metrics=False)
    tweet = _tweet()
    tweet["author"] = None
    tweet["url"] = "https://x.com/testuser/status/123456"
    _install_transport(monkeypatch, lambda request: _response(request, {"tweets": [tweet]}))

    result = json.loads(tools.search_posts("agents"))

    assert result["posts"][0]["author"] == {
        "id": "",
        "name": "",
        "username": "",
        "verified": False,
    }
    assert result["posts"][0]["url"] == "https://x.com/testuser/status/123456"
    assert "metrics" not in result["posts"][0]


@pytest.mark.parametrize("status_code", [301, 302, 307, 308])
def test_requests_reject_redirects_without_forwarding_credentials(
    xquik_tools: XquikTools, monkeypatch: pytest.MonkeyPatch, status_code: int
) -> None:
    requests = _install_transport(
        monkeypatch,
        lambda request: httpx.Response(
            status_code,
            headers={"location": "https://attacker.example/collect"},
            request=request,
        ),
    )

    result = json.loads(xquik_tools.search_posts("agents"))

    assert "error" in result
    assert len(requests) == 1
    assert requests[0].url.host == "xquik.com"


def test_get_user_info_encodes_identifier(xquik_tools: XquikTools, monkeypatch: pytest.MonkeyPatch) -> None:
    requests = _install_transport(
        monkeypatch,
        lambda request: _response(
            request,
            {
                "id": "1",
                "name": "Agno",
                "username": "AgnoAgi",
                "description": "Build agents",
                "followers": 50000,
                "following": 100,
                "statusesCount": 2000,
                "verified": True,
            },
        ),
    )

    result = json.loads(xquik_tools.get_user_info("@team/user"))

    assert requests[0].url.path == "/api/v1/x/users/team/user"
    assert requests[0].url.raw_path.endswith(b"team%2Fuser")
    assert result["username"] == "AgnoAgi"
    assert result["followers_count"] == 50000


@pytest.mark.asyncio
async def test_async_get_user_info(xquik_tools: XquikTools, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_transport(
        monkeypatch,
        lambda request: _response(request, {"id": "1", "name": "Agno", "username": "AgnoAgi"}),
    )

    result = json.loads(await xquik_tools.aget_user_info("AgnoAgi"))

    assert result["url"] == "https://x.com/AgnoAgi"


def test_get_tweet_maps_response_envelope(xquik_tools: XquikTools, monkeypatch: pytest.MonkeyPatch) -> None:
    data = {
        "tweet": {key: value for key, value in _tweet().items() if key != "author"},
        "author": {"id": "789", "name": "Test User", "username": "testuser", "verified": True},
    }
    requests = _install_transport(monkeypatch, lambda request: _response(request, data))

    result = json.loads(xquik_tools.get_tweet("12/34"))

    assert requests[0].url.raw_path.endswith(b"12%2F34")
    assert result["author"]["username"] == "testuser"


@pytest.mark.asyncio
async def test_async_get_tweet_rejects_invalid_envelope(
    xquik_tools: XquikTools, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_transport(monkeypatch, lambda request: _response(request, {"tweet": None}))

    result = json.loads(await xquik_tools.aget_tweet("123"))

    assert result == {"error": "Xquik returned an invalid tweet response."}


def test_get_user_posts_sends_bounded_page_size_and_filters(
    xquik_tools: XquikTools, monkeypatch: pytest.MonkeyPatch
) -> None:
    requests = _install_transport(
        monkeypatch,
        lambda request: _response(
            request,
            {"tweets": [], "has_next_page": True, "next_cursor": "cursor-2"},
        ),
    )

    result = json.loads(
        xquik_tools.get_user_posts(
            "@AgnoAgi",
            max_results=500,
            cursor="cursor-1",
            include_replies=True,
            include_parent_tweet=True,
        )
    )

    params = requests[0].url.params
    assert params["pageSize"] == "100"
    assert params["includeReplies"] == "true"
    assert params["includeParentTweet"] == "true"
    assert result["next_cursor"] == "cursor-2"


@pytest.mark.asyncio
async def test_async_get_user_posts(xquik_tools: XquikTools, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_transport(monkeypatch, lambda request: _response(request, {"tweets": [_tweet()]}))

    result = json.loads(await xquik_tools.aget_user_posts("AgnoAgi"))

    assert result["count"] == 1


def test_get_trends_uses_current_route(xquik_tools: XquikTools, monkeypatch: pytest.MonkeyPatch) -> None:
    requests = _install_transport(
        monkeypatch,
        lambda request: _response(request, {"total": 1, "trends": [{"name": "#AI"}], "woeid": 1}),
    )

    result = json.loads(xquik_tools.get_trends(count=100))

    assert requests[0].url.path == "/api/v1/trends"
    assert requests[0].url.params["count"] == "50"
    assert result == {"trends": [{"name": "#AI"}], "total": 1, "woeid": 1}


@pytest.mark.asyncio
async def test_async_get_trends(xquik_tools: XquikTools, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_transport(
        monkeypatch,
        lambda request: _response(request, {"total": 0, "trends": [], "woeid": 23424969}),
    )

    result = json.loads(await xquik_tools.aget_trends(woeid=23424969))

    assert result == {"trends": [], "total": 0, "woeid": 23424969}


def test_get_trends_rejects_invalid_response(xquik_tools: XquikTools, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_transport(monkeypatch, lambda request: _response(request, {"trends": ["invalid"]}))

    result = json.loads(xquik_tools.get_trends())

    assert result["error"] == "Xquik returned an invalid trends response."


def test_missing_key_and_http_errors_return_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XQUIK_API_KEY", raising=False)
    tools = XquikTools()
    result = json.loads(tools.search_posts("agents"))
    assert result["error"] == "XQUIK_API_KEY not set. Set the environment variable or pass api_key."

    keyed_tools = XquikTools(api_key="xq_test_key")
    _install_transport(monkeypatch, lambda request: _response(request, {"error": "limited"}, 429))
    result = json.loads(keyed_tools.search_posts("agents"))
    assert "429" in result["error"]
