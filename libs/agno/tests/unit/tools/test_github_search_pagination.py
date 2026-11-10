"""Exercise GitHub search pagination through the real SDK with offline HTTP."""

import json
from urllib.parse import parse_qs, urlparse

import pytest
import requests
from github import Github

from agno.tools.github import GithubTools


class SearchAPI:
    """Return ordered search results using GitHub's page/per_page contract."""

    def __init__(self):
        self.total = 235
        self.error_status = None
        self.requests = []
        self.closed_clients = []

    def respond(self, request):
        self.requests.append(request)
        parsed = urlparse(request.url)
        assert request.method == "GET"
        assert parsed.path.endswith(("/search/repositories", "/search/issues"))
        parameters = parse_qs(parsed.query)
        page = int(parameters.get("page", ["1"])[0])
        per_page = int(parameters.get("per_page", ["30"])[0])
        offset = (page - 1) * per_page

        response = requests.Response()
        response.url = request.url
        response.headers["Content-Type"] = "application/json"
        response.status_code = self.error_status or (422 if offset >= 1000 else 200)
        if response.status_code != 200:
            body = {"message": "Only the first 1000 search results are available" if offset >= 1000 else "Forbidden"}
        else:
            items = []
            for number in range(offset + 1, min(offset + per_page, self.total, 1000) + 1):
                if parsed.path.endswith("/search/repositories"):
                    item = {
                        "full_name": f"owner/repository-{number}",
                        "description": "Search result",
                        "html_url": f"https://github.com/owner/repository-{number}",
                        "stargazers_count": number,
                        "forks_count": 0,
                        "language": "Python",
                    }
                else:
                    item = {
                        "number": number,
                        "title": f"Issue {number}",
                        # Preload repository details to isolate pagination from SDK lazy-loading requests.
                        "repository": {"full_name": "owner/repository"},
                        "state": "open",
                        "created_at": "2026-01-01T00:00:00Z",
                        "updated_at": "2026-01-01T00:00:00Z",
                        "html_url": f"https://github.com/owner/repository/issues/{number}",
                        "user": {"login": "owner"},
                        "pull_request": None,
                        "comments": 0,
                        "labels": [],
                    }
                items.append(item)
            body = {"total_count": self.total, "incomplete_results": False, "items": items}
            if offset + per_page < min(self.total, 1000):
                response.headers["Link"] = (
                    f"<{parsed.scheme}://{parsed.netloc}{parsed.path}"
                    f'?q=sample&page={page + 1}&per_page={per_page}>; rel="next"'
                )
        response._content = json.dumps(body).encode()
        return response


@pytest.fixture
def search_api(monkeypatch):
    api = SearchAPI()
    original_close = Github.close

    def send(session, request, **kwargs):
        return api.respond(request)

    def close(client):
        api.closed_clients.append(client)
        original_close(client)

    monkeypatch.setattr(requests.Session, "send", send)
    monkeypatch.setattr(Github, "close", close)
    return api


def search(toolkit, method, **kwargs):
    return json.loads(getattr(toolkit, method)("sample", **kwargs))


def result_numbers(result, method):
    if method == "search_repositories":
        return [int(item["full_name"].rsplit("-", 1)[1]) for item in result]
    return [item["number"] for item in result["results"]]


SEARCH_METHODS = ["search_repositories", "search_issues_and_prs"]


@pytest.mark.parametrize("method", SEARCH_METHODS)
@pytest.mark.parametrize(
    "per_page, expected_size, first_page, second_page",
    [
        (10, 10, (1, 10), (11, 20)),
        (None, 30, (1, 30), (31, 60)),
        (100, 100, (1, 100), (101, 200)),
        (150, 100, (1, 100), (101, 200)),
    ],
)
def test_search_pages_use_requested_size(search_api, method, per_page, expected_size, first_page, second_page):
    toolkit = GithubTools(access_token="offline-test-token")
    kwargs = {} if per_page is None else {"per_page": per_page}

    for page, (first, last) in enumerate((first_page, second_page), start=1):
        result = search(toolkit, method, page=page, **kwargs)

        assert result_numbers(result, method) == list(range(first, last + 1))
        parameters = parse_qs(urlparse(search_api.requests[-1].url).query)
        assert int(parameters.get("per_page", ["30"])[0]) == expected_size
        assert int(parameters.get("page", ["1"])[0]) == page
        if method == "search_issues_and_prs":
            assert result["total_count"] == 235
            assert result["per_page"] == expected_size
            assert result["results_count"] == expected_size
            assert result["page"] == page

    assert len(search_api.requests) == 2


@pytest.mark.parametrize("method", SEARCH_METHODS)
def test_search_handles_empty_partial_and_out_of_range_pages(search_api, method):
    toolkit = GithubTools(access_token="offline-test-token")

    for total, page, expected in [(0, 1, []), (15, 2, [11, 12, 13, 14, 15]), (15, 3, [])]:
        search_api.total = total
        result = search(toolkit, method, page=page, per_page=10)
        assert result_numbers(result, method) == expected
        if method == "search_issues_and_prs":
            assert result["total_count"] == total
            assert result["results_count"] == len(expected)

    assert len(search_api.requests) == 3


@pytest.mark.parametrize("method", SEARCH_METHODS)
def test_search_fetches_deep_page_once_and_preserves_api_limit_error(search_api, method):
    search_api.total = 1200
    toolkit = GithubTools(access_token="offline-test-token")

    result = search(toolkit, method, page=10, per_page=100)

    assert result_numbers(result, method) == list(range(901, 1001))
    assert len(search_api.requests) == 1
    if method == "search_issues_and_prs":
        assert result["total_count"] == 1200

    error = search(toolkit, method, page=11, per_page=100)
    assert "1000" in error["error"]
    assert len(search_api.requests) == 2


def test_different_search_page_sizes_leave_shared_client_unchanged(search_api):
    toolkit = GithubTools(access_token="offline-test-token")
    shared_client = toolkit.g

    for method, per_page, first, last in [
        ("search_repositories", 10, 11, 20),
        ("search_issues_and_prs", 100, 101, 200),
        ("search_repositories", 30, 31, 60),
    ]:
        result = search(toolkit, method, page=2, per_page=per_page)
        assert result_numbers(result, method) == list(range(first, last + 1))
        assert toolkit.g is shared_client
        assert shared_client.per_page == 30

    assert len(search_api.closed_clients) == 3
    assert all(client is not shared_client for client in search_api.closed_clients)


@pytest.mark.parametrize("method", SEARCH_METHODS)
def test_search_preserves_enterprise_url_auth_and_query_options(search_api, method):
    toolkit = GithubTools(access_token="offline-test-token", base_url="https://github.example.test/api/v3")
    kwargs = {"repo": "owner/repository", "state": "open", "type_filter": "issue"} if method.endswith("prs") else {}

    result = search(toolkit, method, page=2, per_page=10, sort="updated", order="asc", **kwargs)

    assert result_numbers(result, method) == list(range(11, 21))
    request = search_api.requests[0]
    parsed = urlparse(request.url)
    assert parsed.hostname == "github.example.test"
    assert parsed.path == "/api/v3/search/" + ("repositories" if method == "search_repositories" else "issues")
    assert request.headers["Authorization"] == "token offline-test-token"
    parameters = parse_qs(parsed.query)
    assert parameters["sort"] == ["updated"]
    assert parameters["order"] == ["asc"]
    assert parameters["q"] == ["sample state:open is:issue repo:owner/repository" if kwargs else "sample"]


@pytest.mark.parametrize("method", SEARCH_METHODS)
def test_search_closes_its_client_after_http_error(search_api, method):
    search_api.error_status = 403
    toolkit = GithubTools(access_token="offline-test-token")

    result = search(toolkit, method, page=2, per_page=10)

    assert "Forbidden" in result["error"]
    assert len(search_api.requests) == 1
    assert len(search_api.closed_clients) == 1
    assert search_api.closed_clients[0] is not toolkit.g
    assert toolkit.g.per_page == 30


@pytest.mark.parametrize("method", SEARCH_METHODS)
def test_search_rejects_nonpositive_pagination_without_requests(search_api, method):
    toolkit = GithubTools(access_token="offline-test-token")

    for kwargs in [{"page": 0}, {"page": -1}, {"per_page": 0}, {"per_page": -1}]:
        result = search(toolkit, method, **kwargs)
        assert "error" in result

    assert search_api.requests == []
