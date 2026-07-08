"""Unit tests for CustomApiTools class."""

import json

import pytest

from agno.tools.api import CustomApiTools


def _skip_if_upstream_down(data: dict) -> None:
    # dog.ceo is a live third-party service; a 5xx from it (Cloudflare 520s are
    # common), a transport-level failure (SSL/connection errors yield an
    # "error" dict with no status_code), or a non-JSON error page (outages
    # serve an HTML 404 in place of the API's JSON envelope) says nothing
    # about our code, so it must not red the build. A non-200 with the JSON
    # envelope still fails: that is dog.ceo answering that we asked for a
    # route it does not have.
    if "status_code" not in data:
        pytest.skip(f"dog.ceo unreachable: {data.get('error', 'no response')}")
    if data["status_code"] >= 500:
        pytest.skip(f"dog.ceo unavailable (HTTP {data['status_code']})")
    if data["status_code"] != 200 and "text" in data["data"]:
        pytest.skip(f"dog.ceo unavailable (HTTP {data['status_code']}, non-JSON body)")


def test_integration_dog_api():
    """Integration test with actual Dog API (optional, can be skipped in CI)."""
    # This test makes actual API calls - can be skipped in CI environments
    # by using pytest.mark.skipif if needed
    tools = CustomApiTools(base_url="https://dog.ceo/api")

    # Test random image endpoint
    image_result = tools.make_request(
        endpoint="/breeds/image/random",
        method="GET",
    )
    image_data = json.loads(image_result)
    _skip_if_upstream_down(image_data)
    assert image_data["status_code"] == 200
    assert "message" in image_data["data"]
    assert "https://images.dog.ceo" in image_data["data"]["message"]

    # Test breeds list endpoint
    breeds_result = tools.make_request(
        endpoint="/breeds/list/all",
        method="GET",
    )
    breeds_data = json.loads(breeds_result)
    _skip_if_upstream_down(breeds_data)
    assert breeds_data["status_code"] == 200
    assert "message" in breeds_data["data"]
    assert isinstance(breeds_data["data"]["message"], dict)
    assert len(breeds_data["data"]["message"]) > 0
