from typing import Optional

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
    ):
        super().__init__(name="aws_ses_tool", tools=[self.send_email])
        self.client = boto3.client("ses", region_name=region_name)
        self.sender_email = sender_email
        self.sender_name = sender_name

    def send_email(self, subject: str, body: str, receiver_email: str) -> str:
        """
        Use this tool to send an email using AWS SES.

        Args: subject: The subject of the email
                body: The body of the email
                receiver_email: The email address of the receiver
        """
        if not self.client:
            raise Exception("AWS SES client not initialized. Please check the configuration.")
        if not subject:
            return "Email subject cannot be empty."
        if not body:
            return "Email body cannot be empty."
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
            return "Email sent successfully!"
        except Exception as e:
            raise Exception(f"Failed to send email: {e}")
