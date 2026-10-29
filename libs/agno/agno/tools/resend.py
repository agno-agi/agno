import re
from os import getenv
from typing import Any, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_error, log_info, log_warning, logger

try:
    import resend  # type: ignore
except ImportError:
    raise ImportError("`resend` not installed. Please install using `pip install resend`.")


# Minimal email address validation: <local>@<domain>.<tld>
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class ResendTools(Toolkit):
    def __init__(
        self,
        api_key: Optional[str] = None,
        from_email: Optional[str] = None,
        enable_send_email: bool = True,
        require_confirmation: bool = False,
        allowed_emails: Optional[List[str]] = None,
        allowed_domains: Optional[List[str]] = None,
        all: bool = False,
        **kwargs,
    ):
        """Initialize ResendTools.

        .. warning::
            ``send_email`` sends an arbitrary recipient/subject/body using the
            host's Resend API key. By default this is a data-exfiltration sink if
            the agent is prompt-injected. To harden it, set
            ``require_confirmation=True`` (gates every send behind human approval)
            and/or restrict recipients via ``allowed_emails`` / ``allowed_domains``.

        Args:
            api_key: Resend API key. Falls back to the ``RESEND_API_KEY`` env var.
            from_email: The ``From`` address.
            enable_send_email: Register the ``send_email`` tool.
            require_confirmation: If True, mark ``send_email`` as requiring
                human-in-the-loop confirmation before execution.
            allowed_emails: Allowlist of exact recipient addresses. If set, only
                these recipients may receive mail.
            allowed_domains: Allowlist of recipient domains (e.g. ``["example.com"]``).
                If set, every recipient's domain must be listed. Combined with
                ``allowed_emails`` — a recipient passes if it matches either list.
            all: Register all tools.
        """
        self.from_email = from_email
        self.api_key = api_key or getenv("RESEND_API_KEY")
        if not self.api_key:
            log_error("No Resend API key provided")

        self.allowed_emails = [e.lower().strip() for e in allowed_emails] if allowed_emails else None
        self.allowed_domains = [d.lower().strip().lstrip(".") for d in allowed_domains] if allowed_domains else None

        tools: List[Any] = []
        if all or enable_send_email:
            tools.append(self.send_email)

        super().__init__(
            name="resend_tools",
            tools=tools,
            requires_confirmation_tools=["send_email"] if require_confirmation else None,
            **kwargs,
        )

    def _validate_recipient(self, to_email: str) -> Optional[str]:
        """Validate a comma-separated recipient list against format + allowlists.

        Returns an error message string if any recipient is invalid/blocked, or
        None if all recipients are allowed.
        """
        recipients = [r.strip() for r in to_email.split(",") if r.strip()]
        if not recipients:
            return "Error: Please provide an email address to send the email to."

        has_allowlist = self.allowed_emails is not None or self.allowed_domains is not None

        for recipient in recipients:
            if not _EMAIL_RE.match(recipient):
                return f"Error: Invalid email address: {recipient}"

            if has_allowlist:
                normalized = recipient.lower()
                domain = normalized.rsplit("@", 1)[-1] if "@" in normalized else ""
                email_ok = self.allowed_emails is not None and normalized in self.allowed_emails
                domain_ok = self.allowed_domains is not None and domain in self.allowed_domains
                if not email_ok and not domain_ok:
                    return f"Error: Recipient '{recipient}' is not in the allowed emails/domains list."

        return None

    def send_email(self, to_email: str, subject: str, body: str) -> str:
        """Send an email using the Resend API. Returns if the email was sent successfully or an error message.

        .. warning::
            The recipient and body are model-controlled. Harden this tool via
            ``require_confirmation=True`` and/or ``allowed_emails`` /
            ``allowed_domains`` on ``ResendTools`` to prevent data exfiltration.

        :to_email: The email address to send the email to.
        :subject: The subject of the email.
        :body: The body of the email.
        :return: A string indicating if the email was sent successfully or an error message.
        """

        if not self.api_key:
            return "Error: Please provide an API key"

        validation_error = self._validate_recipient(to_email)
        if validation_error is not None:
            log_warning(f"Blocked send_email: {validation_error}")
            return validation_error

        log_info(f"Sending email to: {to_email}")

        resend.api_key = self.api_key
        try:
            if not self.from_email:
                return "Error: Please provide a from_email address"
            params = {
                "from": self.from_email,
                "to": to_email,
                "subject": subject,
                "html": body,
            }

            # resend expects its typed SendParams; we build a plain dict as the
            # original implementation did. SDK typing mismatch is ignored.
            resend.Emails.send(params)  # type: ignore[arg-type]
            return f"Email sent to {to_email} successfully."
        except Exception as e:
            logger.exception("Failed to send email")
            return f"Error: {e}"
