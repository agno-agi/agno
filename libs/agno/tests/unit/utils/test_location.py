"""Tests for the IP geolocation helper."""

from unittest.mock import Mock

import httpx
import pytest

from agno.utils.location import get_location


def test_get_location_returns_ip_geolocation(monkeypatch):
    ip_response = Mock()
    ip_response.json.return_value = {"ip": "203.0.113.7"}
    location_response = Mock(status_code=200)
    location_response.json.return_value = {"city": "Paris", "region": "Ile-de-France", "country": "France"}
    mock_get = Mock(side_effect=[ip_response, location_response])
    monkeypatch.setattr(httpx, "get", mock_get)

    assert get_location() == {"city": "Paris", "region": "Ile-de-France", "country": "France"}
    assert mock_get.call_args_list[0].args == ("https://api.ipify.org?format=json",)
    assert mock_get.call_args_list[1].args == ("http://ip-api.com/json/203.0.113.7",)


def test_get_location_returns_empty_dict_on_http_error(monkeypatch):
    monkeypatch.setattr(httpx, "get", Mock(side_effect=httpx.ConnectError("offline")))

    assert get_location() == {}


def test_get_location_returns_empty_dict_when_lookup_is_not_ok(monkeypatch):
    """A non-200 from the geolocation host is a miss, not a location."""
    ip_response = Mock()
    ip_response.json.return_value = {"ip": "203.0.113.7"}
    location_response = Mock(status_code=503)
    monkeypatch.setattr(httpx, "get", Mock(side_effect=[ip_response, location_response]))

    assert get_location() == {}


@pytest.mark.parametrize(
    "error",
    [
        httpx.ConnectError("offline"),
        httpx.ConnectTimeout("slow"),
        httpx.InvalidURL("bad url"),
        httpx.CookieConflict("conflict"),
        httpx.StreamError("stream"),
        ValueError("not json"),
        KeyError("ip"),
        RuntimeError("anything else"),
    ],
    ids=[
        "connect-error",
        "timeout",
        "invalid-url",
        "cookie-conflict",
        "stream-error",
        "bad-json",
        "missing-ip-key",
        "unexpected",
    ],
)
def test_get_location_swallows_every_failure(monkeypatch, error):
    """`get_location()` runs inline while a system message is being built, so
    every failure has to come back as an empty dict. `httpx.InvalidURL`,
    `CookieConflict` and `StreamError` are not `httpx.HTTPError` subclasses,
    so catching only `HTTPError` would let them reach the run."""
    monkeypatch.setattr(httpx, "get", Mock(side_effect=error))

    assert get_location() == {}


def test_get_location_survives_a_malformed_geolocation_payload(monkeypatch):
    """The second response parses but carries none of the expected keys."""
    ip_response = Mock()
    ip_response.json.return_value = {"ip": "203.0.113.7"}
    location_response = Mock(status_code=200)
    location_response.json.return_value = {}
    monkeypatch.setattr(httpx, "get", Mock(side_effect=[ip_response, location_response]))

    assert get_location() == {"city": None, "region": None, "country": None}


def test_get_location_does_not_import_requests():
    """The fix exists because `requests` is not a declared dependency."""
    import agno.utils.location as location_module

    assert not hasattr(location_module, "requests")
