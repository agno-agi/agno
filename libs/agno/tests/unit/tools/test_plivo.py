"""Unit tests for Plivo Tools"""

from unittest.mock import Mock, patch

import pytest

from agno.tools.plivo import PlivoTools


@pytest.fixture(autouse=True)
def mock_rest_client():
    with patch("plivo.RestClient") as mock_client_cls:
        mock_client_cls.return_value = Mock()
        yield mock_client_cls


class TestPlivoTools:
    """Test cases for PlivoTools"""

    def test_initialization(self, mock_rest_client):
        """Test tool initialization and default tool registration"""
        tool = PlivoTools(auth_id="test-auth-id", auth_token="test-auth-token")

        mock_rest_client.assert_called_once_with(auth_id="test-auth-id", auth_token="test-auth-token")
        assert tool.client is mock_rest_client.return_value
        assert tool.name == "plivo"
        assert set(tool.functions.keys()) == {
            "send_sms",
            "make_call",
            "get_call_details",
            "list_messages",
            "list_calls",
            "lookup_number",
        }

    def test_disabled_flag_unregisters_tool(self):
        """A disabled enable_* flag keeps that function out of the registry"""
        tool = PlivoTools(auth_id="id", auth_token="token", enable_send_sms=False)

        assert "send_sms" not in tool.functions
        assert "make_call" in tool.functions

    def test_validate_phone_number(self):
        """E.164 validation accepts valid numbers and rejects malformed ones"""
        assert PlivoTools.validate_phone_number("+14155551234") is True
        assert PlivoTools.validate_phone_number("14155551234") is False
        assert PlivoTools.validate_phone_number("+0155551234") is False
        assert PlivoTools.validate_phone_number("not-a-number") is False

    def test_send_sms_success(self):
        """send_sms maps to Plivo's src/dst/text and returns the message UUID"""
        tool = PlivoTools(auth_id="id", auth_token="token")
        tool.client.messages.create.return_value = Mock(message_uuid=["abc-123"])

        result = tool.send_sms(to="+14155551234", from_="+14155550000", body="hello")

        tool.client.messages.create.assert_called_once_with(src="+14155550000", dst="+14155551234", text="hello")
        assert "abc-123" in result

    def test_send_sms_rejects_non_e164(self):
        """send_sms fails closed on a non-E.164 recipient and never calls the API"""
        tool = PlivoTools(auth_id="id", auth_token="token")

        result = tool.send_sms(to="14155551234", from_="+14155550000", body="hello")

        assert "E.164" in result
        tool.client.messages.create.assert_not_called()

    def test_send_sms_allows_alphanumeric_sender(self):
        """src may be an alphanumeric sender ID or short code, not only an E.164 number"""
        tool = PlivoTools(auth_id="id", auth_token="token")
        tool.client.messages.create.return_value = Mock(message_uuid=["abc-123"])

        result = tool.send_sms(to="+14155551234", from_="PLIVO", body="hello")

        tool.client.messages.create.assert_called_once_with(src="PLIVO", dst="+14155551234", text="hello")
        assert "abc-123" in result

    def test_make_call_success(self):
        """make_call maps to Plivo's from_/to_/answer_url/answer_method and returns the request UUID"""
        tool = PlivoTools(auth_id="id", auth_token="token")
        tool.client.calls.create.return_value = Mock(request_uuid="req-9")

        result = tool.make_call(
            to="+14155551234", from_="+14155550000", answer_url="https://example.com/answer.xml", answer_method="GET"
        )

        tool.client.calls.create.assert_called_once_with(
            from_="+14155550000", to_="+14155551234", answer_url="https://example.com/answer.xml", answer_method="GET"
        )
        assert "req-9" in result

    def test_make_call_rejects_non_e164(self):
        """make_call fails closed on a non-E.164 recipient and never calls the API"""
        tool = PlivoTools(auth_id="id", auth_token="token")

        result = tool.make_call(to="14155551234", from_="+14155550000", answer_url="https://example.com/answer.xml")

        assert "E.164" in result
        tool.client.calls.create.assert_not_called()

    def test_make_call_rejects_bad_answer_method(self):
        """make_call rejects an answer_method other than GET/POST"""
        tool = PlivoTools(auth_id="id", auth_token="token")

        result = tool.make_call(
            to="+14155551234", from_="+14155550000", answer_url="https://example.com/answer.xml", answer_method="DELETE"
        )

        assert "GET or POST" in result
        tool.client.calls.create.assert_not_called()

    def test_list_messages_clamps_limit_to_plivo_max(self):
        """limit is clamped to Plivo's per-request max of 20 (the SDK rejects >20)"""
        tool = PlivoTools(auth_id="id", auth_token="token")
        tool.client.messages.list.return_value = []

        tool.list_messages(limit=100)

        tool.client.messages.list.assert_called_once_with(limit=20, offset=0, message_direction=None)

    def test_list_messages_forwards_offset_and_direction(self):
        """offset and message_direction are forwarded to the Plivo list call"""
        tool = PlivoTools(auth_id="id", auth_token="token")
        tool.client.messages.list.return_value = []

        tool.list_messages(limit=5, offset=20, message_direction="inbound")

        tool.client.messages.list.assert_called_once_with(limit=5, offset=20, message_direction="inbound")

    def test_list_messages_normalizes_empty_direction(self):
        """An empty message_direction is normalized to None (the SDK rejects the empty string)"""
        tool = PlivoTools(auth_id="id", auth_token="token")
        tool.client.messages.list.return_value = []

        tool.list_messages(message_direction="")

        tool.client.messages.list.assert_called_once_with(limit=20, offset=0, message_direction=None)

    def test_list_messages_rejects_bad_direction(self):
        """list_messages rejects a direction other than inbound/outbound and never calls the API"""
        tool = PlivoTools(auth_id="id", auth_token="token")

        result = tool.list_messages(message_direction="sideways")

        assert "message_direction" in result[0]["error"]
        tool.client.messages.list.assert_not_called()

    def test_list_calls_clamps_limit_and_forwards_paging(self):
        """list_calls clamps limit to 20 and forwards offset/call_direction to the Plivo list call"""
        tool = PlivoTools(auth_id="id", auth_token="token")
        tool.client.calls.list.return_value = []

        tool.list_calls(limit=100, offset=20, call_direction="outbound")

        tool.client.calls.list.assert_called_once_with(limit=20, offset=20, call_direction="outbound")

    def test_list_calls_normalizes_empty_direction(self):
        """An empty call_direction is normalized to None (the SDK rejects the empty string)"""
        tool = PlivoTools(auth_id="id", auth_token="token")
        tool.client.calls.list.return_value = []

        tool.list_calls(call_direction="")

        tool.client.calls.list.assert_called_once_with(limit=20, offset=0, call_direction=None)

    def test_list_calls_rejects_bad_direction(self):
        """list_calls rejects a direction other than inbound/outbound and never calls the API"""
        tool = PlivoTools(auth_id="id", auth_token="token")

        result = tool.list_calls(call_direction="sideways")

        assert "call_direction" in result[0]["error"]
        tool.client.calls.list.assert_not_called()

    def test_lookup_number_success(self):
        """lookup_number returns the carrier and line-type metadata for a number"""
        tool = PlivoTools(auth_id="id", auth_token="token")
        tool.client.lookup.get.return_value = Mock(
            phone_number="+14155551234",
            country={"iso2": "US"},
            carrier={"name": "Acme Wireless", "type": "mobile"},
        )

        result = tool.lookup_number(number="+14155551234")

        tool.client.lookup.get.assert_called_once_with("+14155551234")
        assert result["carrier"]["name"] == "Acme Wireless"

    def test_lookup_number_rejects_non_e164(self):
        """lookup_number fails closed on a non-E.164 number and never calls the API"""
        tool = PlivoTools(auth_id="id", auth_token="token")

        result = tool.lookup_number(number="14155551234")

        assert "E.164" in result["error"]
        tool.client.lookup.get.assert_not_called()
