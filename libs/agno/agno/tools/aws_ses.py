import json
from typing import Callable, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_debug

try:
    import boto3
except ImportError:
    raise ImportError("boto3 is required for AWSSESTool. Please install it using `pip install boto3`.")


class AWSSESTool(Toolkit):
    def __init__(
        self,
        sender_email: Optional[str] = None,
        sender_name: Optional[str] = None,
        region_name: str = "us-east-1",
        send_email: bool = False,
        all: bool = False,
        **kwargs,
    ):
        """Initialize AWS SES toolkit.

        Args:
            sender_email: The email address to send emails from.
            sender_name: The name shown as the email sender.
            region_name: AWS region name. Defaults to "us-east-1".
            send_email: Enable the aws_ses_send_email tool. Defaults to False (sends email).
            all: Enable all tools.
        """
        self.client = boto3.client("ses", region_name=region_name)
        self.sender_email = sender_email
        self.sender_name = sender_name

        tools: List[Callable] = []
        if all or send_email:
            tools.append(self.aws_ses_send_email)

        super().__init__(name="aws_ses_tools", tools=tools, **kwargs)

    def aws_ses_send_email(self, subject: str, body: str, receiver_email: str) -> str:
        """Send an email using AWS SES.

        Args:
            subject: The subject of the email.
            body: The body of the email.
            receiver_email: The email address of the receiver.

        Returns:
            JSON with message_id on success, or error details.
        """
        if not subject:
            return json.dumps({"error": "Email subject cannot be empty"})
        if not body:
            return json.dumps({"error": "Email body cannot be empty"})
        try:
            response = self.client.send_email(
                Source=f"{self.sender_name} <{self.sender_email}>",
                Destination={
                    "ToAddresses": [receiver_email],
                },
                Message={
                    "Body": {
                        "Text": {
                            "Charset": "UTF-8",
                            "Data": body,
                        },
                    },
                    "Subject": {
                        "Charset": "UTF-8",
                        "Data": subject,
                    },
                },
            )
            log_debug(f"Email sent with message ID: {response['MessageId']}")
            return json.dumps({"success": True, "message_id": response["MessageId"]})
        except Exception as e:
            return json.dumps({"error": f"Failed to send email: {e}"})
