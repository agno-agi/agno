"""Unit tests for AWS SES Tool"""

from unittest.mock import Mock, patch

import pytest
from botocore.exceptions import ClientError

from agno.tools.aws_ses import AWSSESTool


class TestAWSSESTool:
    """Test cases for AWSSESTool"""

    @patch("boto3.client")
    def test_initialization_default_region(self, mock_boto_client):
        """Test tool initialization with default region"""
        # Arrange
        mock_client = Mock()
        mock_boto_client.return_value = mock_client

        # Act
        tool = AWSSESTool(sender_email="test@example.com", sender_name="Test Sender")

        # Assert
        mock_boto_client.assert_called_once_with("ses", region_name="us-east-1")
        assert tool.sender_email == "test@example.com"
        assert tool.sender_name == "Test Sender"
        assert tool.client == mock_client
        assert tool.name == "aws_ses_tool"

    @patch("boto3.client")
    def test_initialization_custom_region(self, mock_boto_client):
        """Test tool initialization with custom region"""
        # Arrange
        mock_client = Mock()
        mock_boto_client.return_value = mock_client

        # Act
        AWSSESTool(sender_email="test@example.com", sender_name="Test Sender", region_name="us-west-2")

        # Assert
        mock_boto_client.assert_called_once_with("ses", region_name="us-west-2")

    @patch("boto3.client")
    def test_send_email_success(self, mock_boto_client):
        """Test successful email sending"""
        # Arrange
        mock_client = Mock()
        mock_response = {
            "MessageId": "0101019740cf4f5e-8e090a0f-9edf-4a3d-b5bf-78667b95c2c7-000000",
            "ResponseMetadata": {"RequestId": "test-request-id", "HTTPStatusCode": 200},
        }
        mock_client.send_email.return_value = mock_response
        mock_boto_client.return_value = mock_client

        tool = AWSSESTool(sender_email="sender@example.com", sender_name="Test Sender", region_name="us-west-2")

        # Act
        result = tool.send_email(subject="Test Subject", body="Test Body", receiver_email="receiver@example.com")

        # Assert
        assert result == "Email sent successfully!"
        mock_client.send_email.assert_called_once_with(
            Source="Test Sender <sender@example.com>",
            Destination={
                "ToAddresses": ["receiver@example.com"],
            },
            Message={
                "Body": {
                    "Text": {
                        "Charset": "UTF-8",
                        "Data": "Test Body",
                    },
                },
                "Subject": {
                    "Charset": "UTF-8",
                    "Data": "Test Subject",
                },
            },
        )

    @patch("boto3.client")
    def test_send_email_empty_subject(self, mock_boto_client):
        """Test email sending with empty subject"""
        # Arrange
        mock_client = Mock()
        mock_boto_client.return_value = mock_client

        tool = AWSSESTool(sender_email="sender@example.com", sender_name="Test Sender")

        # Act
        result = tool.send_email(subject="", body="Test Body", receiver_email="receiver@example.com")

        # Assert
        assert result == "Email subject cannot be empty."
        mock_client.send_email.assert_not_called()

    @patch("boto3.client")
    def test_send_email_empty_body(self, mock_boto_client):
        """Test email sending with empty body"""
        # Arrange
        mock_client = Mock()
        mock_boto_client.return_value = mock_client

        tool = AWSSESTool(sender_email="sender@example.com", sender_name="Test Sender")

        # Act
        result = tool.send_email(subject="Test Subject", body="", receiver_email="receiver@example.com")

        # Assert
        assert result == "Email body cannot be empty."
        mock_client.send_email.assert_not_called()

    @patch("boto3.client")
    def test_send_email_invalid_email_format(self, mock_boto_client):
        """Test email sending with invalid email format"""
        # Arrange
        mock_client = Mock()
        mock_error_response = {"Error": {"Code": "InvalidParameterValue", "Message": "Missing final '@domain'"}}
        mock_client.send_email.side_effect = ClientError(mock_error_response, "SendEmail")
        mock_boto_client.return_value = mock_client

        tool = AWSSESTool(sender_email="sender@example.com", sender_name="Test Sender")

        # Act & Assert
        with pytest.raises(Exception) as exc_info:
            tool.send_email(subject="Test Subject", body="Test Body", receiver_email="invalidemailformat")

        assert "Failed to send email" in str(exc_info.value)
        assert "Missing final '@domain'" in str(exc_info.value)

    @patch("boto3.client")
    def test_send_email_aws_error(self, mock_boto_client):
        """Test email sending with AWS error"""
        # Arrange
        mock_client = Mock()
        mock_error_response = {"Error": {"Code": "MessageRejected", "Message": "Email address is not verified."}}
        mock_client.send_email.side_effect = ClientError(mock_error_response, "SendEmail")
        mock_boto_client.return_value = mock_client

        tool = AWSSESTool(sender_email="sender@example.com", sender_name="Test Sender")

        # Act & Assert
        with pytest.raises(Exception) as exc_info:
            tool.send_email(subject="Test Subject", body="Test Body", receiver_email="unverified@example.com")

        assert "Failed to send email" in str(exc_info.value)
        assert "Email address is not verified" in str(exc_info.value)

    @patch("boto3.client")
    def test_send_email_no_client(self, mock_boto_client):
        """Test email sending when client is not initialized"""
        # Arrange
        tool = AWSSESTool(sender_email="sender@example.com", sender_name="Test Sender")
        tool.client = None  # Simulate client not initialized

        # Act & Assert
        with pytest.raises(Exception) as exc_info:
            tool.send_email(subject="Test Subject", body="Test Body", receiver_email="receiver@example.com")

        assert "AWS SES client not initialized" in str(exc_info.value)

    @patch("boto3.client")
    def test_send_email_with_special_characters(self, mock_boto_client):
        """Test email sending with special characters in content"""
        # Arrange
        mock_client = Mock()
        mock_response = {"MessageId": "test-message-id", "ResponseMetadata": {"HTTPStatusCode": 200}}
        mock_client.send_email.return_value = mock_response
        mock_boto_client.return_value = mock_client

        tool = AWSSESTool(sender_email="sender@example.com", sender_name="Test Sender")

        # Act
        result = tool.send_email(
            subject="Test Subject with émojis 🎉",
            body="Body with special chars: ñ, ü, é, 中文, 日本語",
            receiver_email="receiver@example.com",
        )

        # Assert
        assert result == "Email sent successfully!"
        call_args = mock_client.send_email.call_args[1]
        assert call_args["Message"]["Subject"]["Data"] == "Test Subject with émojis 🎉"
        assert "中文" in call_args["Message"]["Body"]["Text"]["Data"]

    @patch("boto3.client")
    def test_send_email_multiple_calls(self, mock_boto_client):
        """Test multiple email sends"""
        # Arrange
        mock_client = Mock()
        mock_response = {"MessageId": "test-message-id", "ResponseMetadata": {"HTTPStatusCode": 200}}
        mock_client.send_email.return_value = mock_response
        mock_boto_client.return_value = mock_client

        tool = AWSSESTool(sender_email="sender@example.com", sender_name="Test Sender")

        # Act
        result1 = tool.send_email(subject="First Email", body="First Body", receiver_email="receiver1@example.com")
        result2 = tool.send_email(subject="Second Email", body="Second Body", receiver_email="receiver2@example.com")

        # Assert
        assert result1 == "Email sent successfully!"
        assert result2 == "Email sent successfully!"
        assert mock_client.send_email.call_count == 2

    def test_import_error_handling(self):
        """Test that import error is handled properly"""
        # This test verifies that the module imports correctly
        # The actual ImportError is raised at module level if boto3 is missing
        from agno.tools.aws_ses import AWSSESTool

        assert AWSSESTool is not None

    @patch("boto3.client")
    def test_send_email_return_message_id(self, mock_boto_client):
        """Test that send_email returns success message with message ID"""
        # Arrange
        mock_client = Mock()
        message_id = "0101019740cf4f5e-8e090a0f-9edf-4a3d-b5bf-78667b95c2c7-000000"
        mock_response = {"MessageId": message_id, "ResponseMetadata": {"HTTPStatusCode": 200}}
        mock_client.send_email.return_value = mock_response
        mock_boto_client.return_value = mock_client

        tool = AWSSESTool(sender_email="sender@example.com", sender_name="Test Sender")

        # Act
        with patch("agno.tools.aws_ses.log_debug") as mock_log:
            result = tool.send_email(subject="Test", body="Test", receiver_email="test@example.com")

            # Assert
            assert result == "Email sent successfully!"
            mock_log.assert_called_once_with(f"Email sent with message ID: {message_id}")
