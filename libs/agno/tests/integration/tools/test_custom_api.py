"""Unit tests for CustomApiTools class."""

import json

from agno.tools.api import CustomApiTools


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
    assert image_data["status_code"] == 200
    assert "message" in image_data["data"]
    assert "https://images.dog.ceo" in image_data["data"]["message"]

    # Test breeds list endpoint
    breeds_result = tools.make_request(
        endpoint="/breeds/list/all",
        method="GET",
    )
    breeds_data = json.loads(breeds_result)
    assert breeds_data["status_code"] == 200
    assert "message" in breeds_data["data"]
    assert isinstance(breeds_data["data"]["message"], dict)
    assert len(breeds_data["data"]["message"]) > 0
