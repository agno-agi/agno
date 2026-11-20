"""Request and response checks for the Rizamo toolkit, with httpx replaced by a recorder."""

import json

import httpx
import pytest

from agno.tools import rizamo as provider
from agno.tools.rizamo import RizamoTools


class Calls(list):
    """The requests the toolkit made, and the answers to give the next ones."""

    def __init__(self):
        super().__init__()
        self.replies = []


@pytest.fixture
def calls(monkeypatch):
    recorded = Calls()

    def fake_request(method, url, **kwargs):
        recorded.append({"method": method, "url": url, **kwargs})
        status, body = recorded.replies.pop(0) if recorded.replies else (200, {"ok": True})
        return httpx.Response(status, json=body, request=httpx.Request(method, url))

    monkeypatch.setattr(provider.httpx, "request", fake_request)
    return recorded


@pytest.fixture
def tools(monkeypatch):
    monkeypatch.setenv("RIZAMO_API_KEY", "rz_test_key")
    return RizamoTools()


def names(toolkit):
    return {tool.__name__ for tool in toolkit.tools}


def test_requires_an_api_key(monkeypatch):
    monkeypatch.delenv("RIZAMO_API_KEY", raising=False)
    with pytest.raises(ValueError, match="RIZAMO_API_KEY"):
        RizamoTools()


def test_explicit_key_overrides_the_environment(monkeypatch, calls):
    monkeypatch.setenv("RIZAMO_API_KEY", "from_env")
    RizamoTools(api_key="explicit").list_profiles()
    assert calls[0]["headers"]["Authorization"] == "Bearer explicit"


@pytest.mark.parametrize(
    "base_url",
    ["http://api.rizamo.com/v1", "https://user:pass@api.rizamo.com/v1", "https://api.rizamo.com/v1?x=1", "ftp://x"],
)
def test_refuses_unsafe_base_urls(base_url):
    with pytest.raises(ValueError, match="base_url"):
        RizamoTools(api_key="k", base_url=base_url)


def test_allows_http_on_loopback():
    assert RizamoTools(api_key="k", base_url="http://127.0.0.1:8787/v1").base_url == "http://127.0.0.1:8787/v1"


def test_publishing_and_replies_are_off_by_default(tools):
    assert names(tools) == {
        "list_profiles",
        "list_accounts",
        "create_post",
        "get_post",
        "add_media",
        "get_analytics",
        "list_threads",
    }


def test_all_enables_every_tool():
    assert {"publish_post", "reply_to_thread"} <= names(RizamoTools(api_key="k", all=True))


def test_flags_turn_tools_off():
    toolkit = RizamoTools(api_key="k", enable_get_analytics=False, enable_list_threads=False)
    assert "get_analytics" not in names(toolkit) and "list_threads" not in names(toolkit)


def test_create_post_saves_a_draft_without_a_time(tools, calls):
    tools.create_post(profile_id="prof_1", text="Hello", account_ids=["acc_1", "acc_2"])
    call = calls[0]
    assert (call["method"], call["url"]) == ("POST", "https://api.rizamo.com/v1/posts")
    assert call["json"] == {
        "profileId": "prof_1",
        "text": "Hello",
        "targets": [{"accountId": "acc_1"}, {"accountId": "acc_2"}],
        "status": "draft",
    }
    assert call["headers"]["Idempotency-Key"]


def test_create_post_schedules_with_a_time_and_media(tools, calls):
    tools.create_post(
        profile_id="prof_1", text="Hi", account_ids=["acc_1"], scheduled_at="2026-12-01T09:00:00Z", media_ids=["med_1"]
    )
    body = calls[0]["json"]
    assert body["status"] == "scheduled"
    assert body["scheduledAt"] == "2026-12-01T09:00:00Z"
    assert body["mediaIds"] == ["med_1"]


def test_each_post_gets_its_own_idempotency_key(tools, calls):
    tools.create_post(profile_id="p", text="a", account_ids=["a"])
    tools.create_post(profile_id="p", text="b", account_ids=["a"])
    assert calls[0]["headers"]["Idempotency-Key"] != calls[1]["headers"]["Idempotency-Key"]


def test_reads_send_no_idempotency_key_and_drop_empty_params(tools, calls):
    tools.list_accounts()
    tools.get_analytics(days=7, profile_id="prof_1")
    assert "Idempotency-Key" not in calls[0]["headers"]
    assert calls[0]["params"] == {}
    assert calls[1]["url"].endswith("/analytics/overview")
    assert calls[1]["params"] == {"days": 7, "profileId": "prof_1"}


def test_paths_of_the_other_tools(calls):
    toolkit = RizamoTools(api_key="k", all=True)
    toolkit.get_post("post_1")
    toolkit.add_media("https://example.com/a.jpg", profile_id="prof_1")
    toolkit.list_threads()
    toolkit.publish_post("post_1")
    toolkit.reply_to_thread("thr_1", "Thanks!")
    assert [(c["method"], c["url"].removeprefix("https://api.rizamo.com/v1")) for c in calls] == [
        ("GET", "/posts/post_1"),
        ("POST", "/media"),
        ("GET", "/inbox/threads"),
        ("POST", "/posts/post_1/publish"),
        ("POST", "/inbox/threads/thr_1/messages"),
    ]
    assert calls[1]["json"] == {"url": "https://example.com/a.jpg", "profileId": "prof_1"}
    assert calls[2]["params"] == {"status": "open"}
    assert calls[4]["json"] == {"text": "Thanks!"}


def test_returns_the_api_answer_as_json(tools, calls):
    calls.replies.append((200, {"items": [{"id": "prof_1"}]}))
    assert json.loads(tools.list_profiles()) == {"items": [{"id": "prof_1"}]}


def test_passes_rizamo_errors_to_the_model(tools, calls):
    calls.replies.append(
        (400, {"error": {"code": "invalid_request", "message": "Account acc_x is not in this profile."}})
    )
    result = json.loads(tools.create_post(profile_id="p", text="x", account_ids=["acc_x"]))
    assert result == {"error": "Account acc_x is not in this profile.", "code": "invalid_request", "status": 400}


def test_network_failures_never_raise_or_leak_the_key(tools, monkeypatch):
    def broken(*args, **kwargs):
        raise httpx.ConnectError("connection refused for rz_test_key")

    monkeypatch.setattr(provider.httpx, "request", broken)
    result = tools.list_profiles()
    assert "rz_test_key" not in result
    assert json.loads(result) == {"error": "Could not reach Rizamo. Try again later."}
