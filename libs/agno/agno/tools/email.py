import json
import smtplib
from email.message import EmailMessage
from typing import Callable, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_info, logger


class EmailTools(Toolkit):
    def __init__(
        self,
        receiver_email: Optional[str] = None,
        sender_name: Optional[str] = None,
        sender_email: Optional[str] = None,
        sender_passkey: Optional[str] = None,
        email_user: bool = True,
        all: bool = False,
        **kwargs,
    ):
        # Backwards compat: enable_X -> X
        if "enable_email_user" in kwargs:
            email_user = kwargs.pop("enable_email_user")

        self.receiver_email: Optional[str] = receiver_email
        self.sender_name: Optional[str] = sender_name
        self.sender_email: Optional[str] = sender_email
        self.sender_passkey: Optional[str] = sender_passkey

        tools: List[Callable] = []
        if all or email_user:
            tools.append(self.email_user)

        super().__init__(name="email_tools", tools=tools, **kwargs)

    def email_user(self, subject: str, body: str) -> str:
        """Send an email to the configured receiver.

        Args:
            subject: The subject of the email.
            body: The body of the email.

        Returns:
            JSON with status or error.
        """
        if not self.receiver_email:
            return json.dumps({"error": "No receiver email provided"})
        if not self.sender_name:
            return json.dumps({"error": "No sender name provided"})
        if not self.sender_email:
            return json.dumps({"error": "No sender email provided"})
        if not self.sender_passkey:
            return json.dumps({"error": "No sender passkey provided"})

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = f"{self.sender_name} <{self.sender_email}>"
        msg["To"] = self.receiver_email
        msg.set_content(body)

        log_info(f"Sending Email to {self.receiver_email}")
        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
                smtp.login(self.sender_email, self.sender_passkey)
                smtp.send_message(msg)
        except Exception as e:
            logger.exception("Error sending email")
            return json.dumps({"error": str(e)})
        return json.dumps({"status": "email sent successfully"})
