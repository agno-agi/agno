"""Unit tests for AnySearchTools.

Mocks every network call: these tests must pass in CI without internet.
Deploy as ``libs/agno/tests/unit/tools/test_anysearch.py``.
"""

import json
from urllib.error import HTTPError

import pytest

from agno.tools.anysearch import AnySearchTools


class _FakeResponse:
    """Stand-in for the object ``urlopen`` returns."""

    def __init__(self, payload):
        self._raw = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _search_payload(n=3):
    return {
        "code": 0,
        "message": "success",
        "data": {
            "results": [
                {
                    "title": f"Title {i}",
                    "url": f"https://example.com/{i}",
                    "snippet": f"snip {i}",
                    "content": f"content {i}",
                }
                for i in range(n)
            ]
        },
    }


def _extract_payload():
    return {
        "code": 0,
        "data": {
            "url": "https://example.com",
            "title": "Example Domain",
            "content": "Body text.",
        },
    }


@pytest.fixture
def recorded(monkeypatch):
    """Patch urlopen and record what each request carried."""
    calls = []

    def handler(request, timeout=None):
        calls.append(
            {
                "url": request.full_url,
                "body": json.loads(request.data.decode("utf-8")),
                "headers": {k.lower(): v for k, v in request.headers.items()},
                "timeout": timeout,
            }
        )
        return _FakeResponse(_search_payload())

    import agno.tools.anysearch as mod

    monkeypatch.setattr(mod, "urlopen", handler)
    return calls


def test_default_registers_both_tools():
    tools = AnySearchTools()
    assert set(tools.functions) == {
        "web_search_using_anysearch",
        "extract_url_content",
    }


def test_flags_control_registration():
    assert set(AnySearchTools(enable_extract=False).functions) == {
        "web_search_using_anysearch"
    }
    assert set(AnySearchTools(enable_search=False).functions) == {
        "extract_url_content"
    }


def test_all_flag_registers_every_tool():
    tools = AnySearchTools(enable_search=False, enable_extract=False, all=True)
    assert len(tools.functions) == 2


@pytest.mark.parametrize(
    "requested,expected",
    [(0, 1), (-5, 1), (999, 20), (7, 7), ("abc", 5), (None, 5)],
)
def test_max_results_is_clamped(requested, expected):
    assert AnySearchTools(max_results=requested).max_results == expected


def test_no_api_key_omits_authorization(recorded):
    AnySearchTools(api_key=None).web_search_using_anysearch("q")
    assert "authorization" not in recorded[0]["headers"]


def test_api_key_sends_bearer(recorded):
    AnySearchTools(api_key="k").web_search_using_anysearch("q")
    assert recorded[0]["headers"]["authorization"] == "Bearer k"


def test_search_payload(recorded):
    AnySearchTools(max_results=4).web_search_using_anysearch("hello")
    assert recorded[0]["url"].endswith("/v1/search")
    assert recorded[0]["body"] == {"query": "hello", "max_results": 4}


def test_vertical_search_payload(recorded):
    tools = AnySearchTools(tag="code.doc", params={"library": "golang"})
    tools.web_search_using_anysearch("generics")
    assert recorded[0]["body"]["tag"] == "code.doc"
    assert recorded[0]["body"]["params"] == {"library": "golang"}


def test_per_call_arguments_win(recorded):
    AnySearchTools(max_results=9).web_search_using_anysearch(
        "x", max_results=2, tag="news", params={"zone": "intl"}
    )
    body = recorded[0]["body"]
    assert body["max_results"] == 2
    assert body["tag"] == "news"
    assert body["params"] == {"zone": "intl"}


def test_extract_payload(monkeypatch):
    import agno.tools.anysearch as mod

    calls = []

    def handler(request, timeout=None):
        calls.append(
            {
                "url": request.full_url,
                "body": json.loads(request.data.decode("utf-8")),
            }
        )
        return _FakeResponse(_extract_payload())

    monkeypatch.setattr(mod, "urlopen", handler)
    AnySearchTools().extract_url_content("https://example.com")
    assert calls[0]["url"].endswith("/v1/extract")
    assert calls[0]["body"] == {"url": "https://example.com"}


def test_results_truncated_to_max_results(monkeypatch):
    import agno.tools.anysearch as mod

    monkeypatch.setattr(
        mod, "urlopen", lambda r, timeout=None: _FakeResponse(_search_payload(n=10))
    )
    out = AnySearchTools(max_results=3, format="json").web_search_using_anysearch("q")
    assert len(json.loads(out)["results"]) == 3


def test_markdown_rendering(monkeypatch):
    import agno.tools.anysearch as mod

    monkeypatch.setattr(
        mod, "urlopen", lambda r, timeout=None: _FakeResponse(_search_payload(n=2))
    )
    out = AnySearchTools(max_results=2).web_search_using_anysearch("q")
    assert out.startswith("# q")
    assert "### [Title 1](https://example.com/1)" in out


def test_extract_renders_markdown(monkeypatch):
    import agno.tools.anysearch as mod

    monkeypatch.setattr(
        mod, "urlopen", lambda r, timeout=None: _FakeResponse(_extract_payload())
    )
    assert AnySearchTools().extract_url_content("https://example.com") == (
        "# Example Domain\n\nBody text."
    )


def test_http_error_degrades(monkeypatch):
    import io

    import agno.tools.anysearch as mod

    def boom(request, timeout=None):
        raise HTTPError(
            "https://api.anysearch.com/v1/search",
            401,
            "err",
            {},
            io.BytesIO(b'{"message":"Invalid API key."}'),
        )

    monkeypatch.setattr(mod, "urlopen", boom)
    out = AnySearchTools().web_search_using_anysearch("q")
    assert "Error searching AnySearch" in out
    assert "401" in out


def test_api_error_code_degrades(monkeypatch):
    import agno.tools.anysearch as mod

    monkeypatch.setattr(
        mod,
        "urlopen",
        lambda r, timeout=None: _FakeResponse(
            {"code": -1, "message": "Invalid API key."}
        ),
    )
    assert "Invalid API key." in AnySearchTools().web_search_using_anysearch("q")


def test_empty_results_degrades(monkeypatch):
    import agno.tools.anysearch as mod

    monkeypatch.setattr(
        mod,
        "urlopen",
        lambda r, timeout=None: _FakeResponse({"code": 0, "data": {"results": []}}),
    )
    assert AnySearchTools().web_search_using_anysearch("q").startswith(
        "No results found"
    )


def test_empty_inputs_rejected():
    tools = AnySearchTools()
    assert "No query provided" in tools.web_search_using_anysearch("   ")
    assert "No URL provided" in tools.extract_url_content("")


def test_timeout_forwarded(recorded):
    AnySearchTools(timeout=13).web_search_using_anysearch("q")
    assert recorded[0]["timeout"] == 13
