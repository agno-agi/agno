"""Exercise the caller's queue decisions and failure fallback."""

import demo
import httpx
import pytest


@pytest.mark.parametrize(
    "content,expected",
    [
        (
            {
                "category": "billing",
                "priority": "normal",
                "order_ids": ["ORD-1042"],
                "needs_review": False,
                "reason": "Duplicate charge",
            },
            "billing-support",
        ),
        (
            {
                "category": "technical",
                "priority": "urgent",
                "order_ids": [],
                "needs_review": False,
                "reason": "Outage",
            },
            "priority-support",
        ),
        (
            {
                "category": "billing",
                "priority": "urgent",
                "order_ids": [],
                "needs_review": True,
                "reason": "Ambiguous",
            },
            "manual-review",
        ),
        ({"category": "invented"}, "manual-review"),
        (None, "manual-review"),
    ],
)
def test_validate_before_routing(monkeypatch, content, expected):
    monkeypatch.setattr(
        demo.httpx,
        "post",
        lambda *args, **kwargs: httpx.Response(
            200,
            json={"content": content},
            request=httpx.Request("POST", "http://localhost"),
        ),
    )
    assert demo.select_queue("customer message") == expected


def test_api_failure_needs_review(monkeypatch):
    def fail(*args, **kwargs):
        raise httpx.ConnectError("unavailable")

    monkeypatch.setattr(demo.httpx, "post", fail)
    assert demo.select_queue("customer message") == "manual-review"
