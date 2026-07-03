"""Unit tests for Plivo Tools"""

from unittest.mock import Mock, patch

from agno.tools.plivo import PlivoTools


class TestPlivoTools:
    """Test cases for PlivoTools"""

    @patch("plivo.RestClient")
    def test_initialization(self, mock_rest_client):
        """Test tool initialization and default tool registration"""
        mock_client = Mock()
        mock_rest_client.return_value = mock_client

        tool = PlivoTools(auth_id="test-auth-id", auth_token="test-auth-token")

        mock_rest_client.assert_called_once_with(auth_id="test-auth-id", auth_token="test-auth-token")
        assert tool.client == mock_client
        assert tool.name == "plivo"
        registered = {t.__name__ for t in [tool.send_sms, tool.get_call_details, tool.list_messages]}
        assert {"send_sms", "get_call_details", "list_messages"} == registered

    def test_validate_phone_number(self):
        """E.164 validation accepts valid numbers and rejects malformed ones"""
        assert PlivoTools.validate_phone_number("+14155551234") is True
        assert PlivoTools.validate_phone_number("14155551234") is False
        assert PlivoTools.validate_phone_number("+0155551234") is False
        assert PlivoTools.validate_phone_number("not-a-number") is False

    @patch("plivo.RestClient")
    def test_send_sms_success(self, mock_rest_client):
        """send_sms maps to Plivo's src/dst/text and returns the message UUID"""
        mock_client = Mock()
        mock_response = Mock()
        mock_response.message_uuid = ["abc-123"]
        mock_client.messages.create.return_value = mock_response
        mock_rest_client.return_value = mock_client

        tool = PlivoTools(auth_id="id", auth_token="token")
        result = tool.send_sms(to="+14155551234", from_="+14155550000", body="hello")

        mock_client.messages.create.assert_called_once_with(src="+14155550000", dst="+14155551234", text="hello")
        assert "abc-123" in result

    @patch("plivo.RestClient")
    def test_send_sms_rejects_non_e164(self, mock_rest_client):
        """send_sms fails closed on a non-E.164 recipient and never calls the API"""
        mock_client = Mock()
        mock_rest_client.return_value = mock_client

        tool = PlivoTools(auth_id="id", auth_token="token")
        result = tool.send_sms(to="14155551234", from_="+14155550000", body="hello")

        assert "E.164" in result
        mock_client.messages.create.assert_not_called()

    @patch("plivo.RestClient")
    def test_send_sms_allows_alphanumeric_sender(self, mock_rest_client):
        """src may be an alphanumeric sender ID or short code, not only an E.164 number"""
        mock_client = Mock()
        mock_response = Mock()
        mock_response.message_uuid = ["abc-123"]
        mock_client.messages.create.return_value = mock_response
        mock_rest_client.return_value = mock_client

        tool = PlivoTools(auth_id="id", auth_token="token")
        result = tool.send_sms(to="+14155551234", from_="PLIVO", body="hello")

        mock_client.messages.create.assert_called_once_with(src="PLIVO", dst="+14155551234", text="hello")
        assert "abc-123" in result

    @patch("plivo.RestClient")
    def test_list_messages_clamps_limit_to_plivo_max(self, mock_rest_client):
        """limit is clamped to Plivo's per-request max of 20 (the SDK rejects >20)"""
        mock_client = Mock()
        mock_client.messages.list.return_value = []
        mock_rest_client.return_value = mock_client

        tool = PlivoTools(auth_id="id", auth_token="token")
        tool.list_messages(limit=100)

        mock_client.messages.list.assert_called_once_with(limit=20)
