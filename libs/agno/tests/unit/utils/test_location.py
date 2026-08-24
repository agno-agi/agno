from unittest.mock import Mock

import httpx

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
