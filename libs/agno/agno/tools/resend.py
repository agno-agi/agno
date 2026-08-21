import json
from os import getenv
from typing import Callable, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_error, log_info

try:
    import resend  # type: ignore
except ImportError:
    raise ImportError("`resend` not installed. Please install using `pip install resend`.")


class ResendTools(Toolkit):
    """Toolkit for sending emails via Resend API.

    Requires a Resend API key. Get one at https://resend.com/api-keys

    Set RESEND_API_KEY environment variable or pass api_key to the constructor.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        from_email: Optional[str] = None,
        send_email: bool = False,
        all: bool = False,
        **kwargs,
    ):
        """Initialize Resend toolkit for sending emails.

        Args:
            api_key: Resend API key. Falls back to RESEND_API_KEY env var.
            from_email: Default sender email address.
            send_email: Enable the send_email tool. Disabled by default (write op).
            all: Enable all tools.
        """
        # Backwards compat: enable_X -> X
        if "enable_send_email" in kwargs:
            send_email = kwargs.pop("enable_send_email")

        self.from_email = from_email
        self.api_key = api_key or getenv("RESEND_API_KEY")
        if not self.api_key:
            log_error("No Resend API key provided")

        tools: List[Callable] = []
        if all or send_email:
            tools.append(self.resend_send_email)

        super().__init__(name="resend_tools", tools=tools, **kwargs)

    def resend_send_email(self, to_email: str, subject: str, body: str) -> str:
        """Send an email using the Resend API.

        Args:
            to_email: Recipient email address.
            subject: Email subject line.
            body: HTML body content.

        Returns:
            JSON with email ID on success or error message.
        """
        if not self.api_key:
            return json.dumps({"error": "No API key configured"})
        if not to_email:
            return json.dumps({"error": "Recipient email address is required"})

        log_info(f"Sending email to: {to_email}")

        resend.api_key = self.api_key
        try:
            params: resend.Emails.SendParams = {
                "to": to_email,
                "subject": subject,
                "html": body,
            }
            if self.from_email:
                params["from"] = self.from_email

            response = resend.Emails.send(params)
            return json.dumps(response)
        except Exception as e:
            log_error(f"Failed to send email: {e}")
            return json.dumps({"error": f"Failed to send email: {e}"})
