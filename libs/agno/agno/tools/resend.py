from os import getenv
from typing import Any, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_info, logger

try:
    import resend  # type: ignore
except ImportError:
    raise ImportError("`resend` not installed. Please install using `pip install resend`.")


class ResendTools(Toolkit):
    def __init__(
        self,
        api_key: Optional[str] = None,
        from_email: Optional[str] = None,
        **kwargs,
    ):
        self.from_email = from_email
        self.api_key = api_key or getenv("RESEND_API_KEY")
        if not self.api_key:
            logger.error("No Resend API key provided")

        tools: List[Any] = []
        tools.append(self.send_email)

        super().__init__(name="resend_tools", tools=tools, **kwargs)

    def send_email(self, to_email: str, subject: str, body: str) -> str:
        """Send an email using the Resend API. Returns if the email was sent successfully or an error message.

        :to_email: The email address to send the email to.
        :subject: The subject of the email.
        :body: The body of the email.
        :return: A string indicating if the email was sent successfully or an error message.
        """

        if not self.api_key:
            return "Please provide an API key"
        if not to_email:
            return "Please provide an email address to send the email to"

        log_info(f"Sending email to: {to_email}")

        resend.api_key = self.api_key
        try:
            params = {
                "from": self.from_email,
                "to": to_email,
                "subject": subject,
                "html": body,
            }

            resend.Emails.send(params)
            return f"Email sent to {to_email} successfully."
        except Exception as e:
            logger.error(f"Failed to send email {e}")
            return f"Error: {e}"
