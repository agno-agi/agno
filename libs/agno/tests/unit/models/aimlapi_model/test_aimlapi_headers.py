"""Tests for the AI/ML API attribution headers.

Every request to AI/ML API carries a fixed set of analytics headers (referer,
title, partner id, source) so the platform can attribute traffic to Agno. They
must reach the OpenAI client's ``default_headers`` without clobbering headers
the caller supplied.
"""

import re

import pytest

from agno.exceptions import ModelAuthenticationError
from agno.models.aimlapi import AIMLAPI, AIMLAPI_HEADERS


def test_attribution_headers_are_sent_by_default():
    """A model built with nothing but an API key still sends every attribution header."""
    client_params = AIMLAPI(api_key="test-key")._get_client_params()

    assert client_params["default_headers"] == AIMLAPI_HEADERS


def test_partner_id_matches_the_gateway_pattern():
    """The gateway only attributes ids shaped part_<alnum>; anything else earns nothing."""
    partner_id = AIMLAPI_HEADERS["X-AIMLAPI-Partner-ID"]

    assert re.fullmatch(r"part_[A-Za-z0-9]{1,64}", partner_id), partner_id


def test_source_is_a_channel_slash_client_slug():
    """AI/ML API parses the source as <channel>/<client>, with a restricted client slug."""
    channel, _, client = AIMLAPI_HEADERS["X-AIMLAPI-Source"].partition("/")

    assert channel == "agent"
    assert re.fullmatch(r"[a-z0-9-]{1,32}", client), client


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
