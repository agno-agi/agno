"""Tests for the AI/ML API attribution headers.

Every request to AI/ML API carries a fixed set of analytics headers (referer,
title, partner id, source) so the platform can attribute traffic to Agno. They
are merged into the model's ``default_headers`` at construction, so they reach
any client built from the model without clobbering headers the caller supplied.
"""

import re

import httpx
import pytest

from agno.exceptions import ModelAuthenticationError
from agno.models.aimlapi import AIMLAPI, AIMLAPI_HEADERS


def test_attribution_headers_are_set_on_the_model():
    """A model built with nothing but an API key carries every attribution header."""
    model = AIMLAPI(api_key="test-key")

    assert model.default_headers == AIMLAPI_HEADERS


def test_attribution_headers_reach_the_client_params():
    """The merged headers flow through to the OpenAI client parameters."""
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

    assert model.default_headers["X-Custom"] == "yes"
    assert model.default_headers["X-Title"] == "Custom Title"
    # Untouched attribution headers survive the merge
    assert model.default_headers["X-AIMLAPI-Partner-ID"] == AIMLAPI_HEADERS["X-AIMLAPI-Partner-ID"]


def test_caller_headers_as_a_list_of_pairs_are_merged():
    """The OpenAI SDK accepts an iterable of (name, value) pairs, so the merge must too."""
    model = AIMLAPI(api_key="test-key", default_headers=[("X-Trace", "1")])

    assert model.default_headers["X-Trace"] == "1"
    assert model.default_headers["X-Title"] == "Agno"


def test_caller_httpx_headers_override_case_insensitively():
    """httpx.Headers lowercases keys; the caller must still win over a differently-cased attribution key."""
    model = AIMLAPI(api_key="test-key", default_headers=httpx.Headers({"X-Title": "Custom Title"}))

    assert model.default_headers is not None
    headers = {key.lower(): value for key, value in dict(model.default_headers).items()}
    assert headers["x-title"] == "Custom Title"
    assert "X-Title" not in dict(model.default_headers)


def test_headers_constant_is_not_mutated_by_a_merge():
    """Merging caller headers must not leak into the shared module-level constant."""
    AIMLAPI(api_key="test-key", default_headers={"X-Title": "Custom Title", "X-AIMLAPI-Partner-ID": "part_other"})

    assert AIMLAPI_HEADERS["X-Title"] == "Agno"
    assert AIMLAPI_HEADERS["X-AIMLAPI-Partner-ID"] == "part_VhLgeTWXXG9RwBOTptNQtcq0"


def test_missing_api_key_raises(monkeypatch):
    """Without a key the model raises before any client is built."""
    monkeypatch.delenv("AIMLAPI_API_KEY", raising=False)

    with pytest.raises(ModelAuthenticationError):
        AIMLAPI(api_key=None)._get_client_params()
