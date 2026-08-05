from os import getenv
from typing import Any, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_error, log_info, logger

try:
    import resend  # type: ignore
except ImportError:
    raise ImportError("`resend` not installed. Please install using `pip install resend`.")


class ResendTools(Toolkit):
    def __init__(
        self,
        api_key: Optional[str] = None,
        from_email: Optional[str] = None,
        enable_send_email: bool = True,
        require_send_email_confirmation: bool = True,
        all: bool = False,
        **kwargs,
    ):
        """
        Initialize ResendTools.

        Args:
            api_key: Resend API key. Defaults to the RESEND_API_KEY environment variable.
            from_email: Email address to send from.
            enable_send_email: Whether to register the send_email tool.
            require_send_email_confirmation: Whether send_email should require user confirmation before execution.
                Disabling this allows agents to send emails without confirmation.
            all: Whether to enable all tools.
            **kwargs: Additional Toolkit options.
        """
        self.from_email = from_email
        self.api_key = api_key or getenv("RESEND_API_KEY")
        if not self.api_key:
            log_error("No Resend API key provided")

        tools: List[Any] = []
        if all or enable_send_email:
            tools.append(self.send_email)

        requires_confirmation_tools = kwargs.pop("requires_confirmation_tools", None)
        if require_send_email_confirmation and (all or enable_send_email):
            if requires_confirmation_tools is None:
                requires_confirmation_tools = ["send_email"]
            elif "send_email" not in requires_confirmation_tools:
                requires_confirmation_tools = [*requires_confirmation_tools, "send_email"]

        super().__init__(
            name="resend_tools",
            tools=tools,
            requires_confirmation_tools=requires_confirmation_tools,
            **kwargs,
        )

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
            logger.exception("Failed to send email")
            return f"Error: {e}"
