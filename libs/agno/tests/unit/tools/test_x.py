"""Unit tests for XTools."""

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

pytest.importorskip("tweepy")

from agno.tools.x import XTools


def test_home_timeline_handles_empty_response():
    """Return an empty timeline when the API response has no data."""
    with patch("agno.tools.x.tweepy.Client") as client_class:
        tools = XTools()
        client_class.return_value.get_home_timeline.return_value = SimpleNamespace(data=None)

        result = json.loads(tools.get_home_timeline())

    assert result == {"home_timeline": []}
    client_class.return_value.get_home_timeline.assert_called_once_with(
        max_results=10,
        tweet_fields=["created_at", "public_metrics"],
    )
