"""Tests for the AI/ML API attribution headers.

Every request to AI/ML API carries a fixed set of analytics headers (referer,
title, partner id, source) so the platform can attribute traffic to Agno. They
must reach the OpenAI client's ``default_headers`` without clobbering headers
the caller supplied.
"""

import pytest

from agno.exceptions import ModelAuthenticationError
from agno.models.aimlapi import AIMLAPI, AIMLAPI_HEADERS


def test_attribution_headers_are_sent_by_default():
    """A model built with nothing but an API key still sends every attribution header."""
    client_params = AIMLAPI(api_key="test-key")._get_client_params()

    assert client_params["default_headers"] == AIMLAPI_HEADERS


def test_partner_id_is_a_part_identifier():
    """The partner id is the rebate-attribution row id and must keep the part_ prefix."""
    assert AIMLAPI_HEADERS["X-AIMLAPI-Partner-ID"].startswith("part_")
    assert AIMLAPI_HEADERS["X-AIMLAPI-Source"] == "agent/agno"


def test_caller_headers_are_merged_and_win_on_conflict():
    """Caller-supplied headers are preserved, and override attribution keys they collide with."""
    model = AIMLAPI(api_key="test-key", default_headers={"X-Custom": "yes", "X-Title": "Custom Title"})

    default_headers = model._get_client_params()["default_headers"]

    assert default_headers["X-Custom"] == "yes"
    assert default_headers["X-Title"] == "Custom Title"
    # Untouched attribution headers survive the merge
    assert default_headers["X-AIMLAPI-Partner-ID"] == AIMLAPI_HEADERS["X-AIMLAPI-Partner-ID"]


def test_headers_constant_is_not_mutated_by_a_merge():
    """Merging caller headers must not leak into the shared module-level constant."""
    AIMLAPI(api_key="test-key", default_headers={"X-Title": "Custom Title"})._get_client_params()

    assert AIMLAPI_HEADERS["X-Title"] == "Agno"


def test_missing_api_key_raises(monkeypatch):
    """Without a key the model raises before any header work happens."""
    monkeypatch.delenv("AIMLAPI_API_KEY", raising=False)

    with pytest.raises(ModelAuthenticationError):
        AIMLAPI(api_key=None)._get_client_params()
