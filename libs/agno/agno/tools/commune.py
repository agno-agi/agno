"""Commune email and SMS tools for AI agents.

Commune provides a programmable email and SMS API built for AI agents.
Unlike SMTP-based solutions, Commune is API-first: agents get a dedicated
inbox address, no SMTP credentials or mail server configuration required.
"""

import re
from datetime import datetime, timezone
from os import getenv
from typing import Any, List, Optional

from agno.tools import Toolkit
from agno.utils.log import logger

try:
    from commune import Commune
except ImportError:
    raise ImportError(
        "commune-mail is required for CommuneTools. "
        "Install it with: pip install commune-mail"
    )


def _relative_time(dt_str: str) -> str:
    """Convert an ISO-8601 timestamp to a human-readable relative time string."""
    try:
        if dt_str.endswith("Z"):
            dt_str = dt_str[:-1] + "+00:00"
        dt = datetime.fromisoformat(dt_str)
        now = datetime.now(tz=timezone.utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        diff = now - dt
        seconds = int(diff.total_seconds())
        if seconds < 60:
            return f"{seconds}s ago"
        if seconds < 3600:
            return f"{seconds // 60}m ago"
        if seconds < 86400:
            return f"{seconds // 3600}h ago"
        return f"{seconds // 86400}d ago"
    except Exception:
        return dt_str


def _format_email_list(emails: List[Any]) -> str:
    """Render a list of email objects into a human-readable, agent-scannable string."""
    if not emails:
        return "No emails found."

    lines: List[str] = []
    for idx, email in enumerate(emails, start=1):
        unread_tag = " | UNREAD" if not email.get("read", True) else ""
        received = _relative_time(email.get("received_at", ""))
        preview_raw = email.get("body", "").strip().replace("\n", " ")
        preview = preview_raw[:80] + "..." if len(preview_raw) > 80 else preview_raw

        header = (
            f"[{idx}] From: {email.get('from_address', 'unknown')} "
            f"| Subject: {email.get('subject', '(no subject)')} "
            f"| Received: {received}{unread_tag}"
        )
        lines.append(header)
        if preview:
            lines.append(f"    Preview: {preview}")
        lines.append("")

    return "\n".join(lines).rstrip()


def _format_sms_list(messages: List[Any]) -> str:
    """Render a list of SMS objects into a human-readable, agent-scannable string."""
    if not messages:
        return "No SMS messages found."

    lines: List[str] = []
    for idx, msg in enumerate(messages, start=1):
        direction = msg.get("direction", "unknown")
        received = _relative_time(msg.get("received_at", ""))
        body_raw = msg.get("body", "").strip().replace("\n", " ")
        body = body_raw[:100] + "..." if len(body_raw) > 100 else body_raw

        if direction == "inbound":
            contact = msg.get("from_number", "unknown")
            direction_label = "FROM"
        else:
            contact = msg.get("to_number", "unknown")
            direction_label = "TO"

        lines.append(f"[{idx}] {direction_label}: {contact} | {received} | {body}")

    return "\n".join(lines)


_E164_RE = re.compile(r"^\+[1-9]\d{1,14}$")


def _validate_e164(number: str) -> bool:
    """Return True if *number* matches the E.164 format (+CCCNNNNNNNNN)."""
    return bool(_E164_RE.match(number))


class CommuneTools(Toolkit):
    """Agno toolkit that wraps the Commune email and SMS API.

    Commune gives AI agents a dedicated inbox and SMS number through a simple
    REST API.  Unlike SMTP-based tools there is no mail server to configure —
    just an API key.

    Args:
        api_key: Commune API key.  Falls back to the ``COMMUNE_API_KEY``
            environment variable when not supplied.
        from_address: Default sender address used by :meth:`send_email` when
            no *from_address* is passed at call time.
        enable_email: Register all email-related tools (default ``True``).
        enable_sms: Register all SMS-related tools (default ``True``).
        **kwargs: Forwarded to :class:`agno.tools.Toolkit`.

    Raises:
        ValueError: When neither *api_key* nor ``COMMUNE_API_KEY`` is set.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        from_address: Optional[str] = None,
        enable_email: bool = True,
        enable_sms: bool = True,
        **kwargs: Any,
    ) -> None:
        resolved_key = api_key or getenv("COMMUNE_API_KEY")
        if not resolved_key:
            raise ValueError(
                "A Commune API key is required. Pass api_key= or set the "
                "COMMUNE_API_KEY environment variable."
            )

        self._client = Commune(api_key=resolved_key)
        self.from_address = from_address

        tools: List[Any] = []
        if enable_email:
            tools.extend(
                [
                    self.send_email,
                    self.read_inbox,
                    self.search_emails,
                    self.get_email,
                ]
            )
        if enable_sms:
            tools.extend(
                [
                    self.send_sms,
                    self.read_sms,
                ]
            )
        # Credits tool is always available regardless of feature flags.
        tools.append(self.get_credits)

        super().__init__(name="commune", tools=tools, **kwargs)

    # ------------------------------------------------------------------
    # Email tools
    # ------------------------------------------------------------------

    def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        from_address: Optional[str] = None,
    ) -> str:
        """Send an email via Commune.

        Use this tool whenever you need to send an outgoing email — for
        example to reply to a support request, notify a user, or deliver a
        report.  The recipient receives a standard email; no special client
        is required on their side.

        Args:
            to: Recipient email address, e.g. ``alice@example.com``.
            subject: Subject line of the email.
            body: Plain-text body of the email.
            from_address: Sender address.  Overrides the default
                ``from_address`` set at initialisation.  When neither is
                provided the Commune API uses your account's default address.

        Returns:
            str: Confirmation string that includes the Commune message ID on
            success, or an error message beginning with ``"Error:"`` on
            failure.
        """
        if not to:
            return "Error: recipient address (to) cannot be empty."
        if not subject:
            return "Error: subject cannot be empty."
        if not body:
            return "Error: body cannot be empty."

        sender = from_address or self.from_address
        try:
            kwargs: dict = {"to": to, "subject": subject, "body": body}
            if sender:
                kwargs["from_address"] = sender
            result = self._client.emails.send(**kwargs)
            msg_id = result.get("id", "unknown")
            status = result.get("status", "unknown")
            logger.debug(f"Email sent: id={msg_id} status={status}")
            return f"Email sent successfully. ID: {msg_id}, status: {status}."
        except Exception as e:
            logger.error(f"send_email failed: {e}")
            return f"Error sending email: {e}"

    def read_inbox(self, limit: int = 10, unread_only: bool = False) -> str:
        """Retrieve and display recent emails from the Commune inbox.

        Use this tool to check what emails have arrived — for example when
        polling for incoming customer support requests, checking for replies,
        or reviewing unread messages before deciding what to act on.

        Args:
            limit: Maximum number of emails to return (default ``10``, max
                determined by Commune plan).
            unread_only: When ``True`` only unread emails are returned
                (default ``False``).

        Returns:
            str: A formatted, human-readable list of emails.  Each entry
            shows the sender, subject, relative receive time, read status,
            and a short body preview.  Returns ``"No emails found."`` when
            the inbox is empty.

            Example output::

                [1] From: alice@example.com | Subject: Meeting tomorrow | Received: 2h ago | UNREAD
                    Preview: Can we move our 3pm meeting to 4pm?

                [2] From: bob@co.com | Subject: Invoice #1042 | Received: 1d ago
                    Preview: Please find attached invoice for...
        """
        try:
            emails = self._client.emails.list(limit=limit, unread_only=unread_only)
            return _format_email_list(emails)
        except Exception as e:
            logger.error(f"read_inbox failed: {e}")
            return f"Error reading inbox: {e}"

    def search_emails(self, query: str, limit: int = 5) -> str:
        """Search emails in the Commune inbox by keyword or phrase.

        Use this tool when you need to find a specific email — for example
        to locate a confirmation, look up a previous conversation, or find
        all emails mentioning a particular topic or sender.

        Args:
            query: Search string.  Matched against sender, subject, and body.
                Example: ``"invoice"`` or ``"from:alice@example.com refund"``.
            limit: Maximum number of matching emails to return (default ``5``).

        Returns:
            str: A formatted list of matching emails in the same layout as
            :meth:`read_inbox`.  Returns ``"No emails found."`` when nothing
            matches.
        """
        if not query:
            return "Error: search query cannot be empty."
        try:
            emails = self._client.emails.search(query=query, limit=limit)
            return _format_email_list(emails)
        except Exception as e:
            logger.error(f"search_emails failed: {e}")
            return f"Error searching emails: {e}"

    def get_email(self, email_id: str) -> str:
        """Fetch the full content of a single email by its ID.

        Use this tool when you need the complete body of an email — for
        example after spotting a relevant message in the inbox list and
        wanting to read it in full before drafting a reply.

        Args:
            email_id: The Commune message ID returned by :meth:`read_inbox`
                or :meth:`search_emails`, e.g. ``"msg_abc123"``.

        Returns:
            str: A formatted string containing the full email details:
            sender, recipient, subject, timestamp, and the complete body.
            Returns an error message on failure.
        """
        if not email_id:
            return "Error: email_id cannot be empty."
        try:
            email = self._client.emails.get(email_id)
            received = _relative_time(email.get("received_at", ""))
            read_status = "read" if email.get("read", False) else "unread"
            output = (
                f"ID: {email.get('id', email_id)}\n"
                f"From: {email.get('from_address', 'unknown')}\n"
                f"To: {email.get('to', 'unknown')}\n"
                f"Subject: {email.get('subject', '(no subject)')}\n"
                f"Received: {received} ({read_status})\n"
                f"---\n"
                f"{email.get('body', '')}"
            )
            # Mark as read after fetching
            try:
                self._client.emails.mark_read(email_id)
            except Exception:
                pass  # Non-fatal; best-effort
            return output
        except Exception as e:
            logger.error(f"get_email failed: {e}")
            return f"Error fetching email {email_id}: {e}"

    # ------------------------------------------------------------------
    # SMS tools
    # ------------------------------------------------------------------

    def send_sms(self, to: str, body: str) -> str:
        """Send an SMS message via Commune.

        Use this tool to send a text message to a phone number — for example
        to alert a user, send an OTP, or notify on-call staff.

        Args:
            to: Destination phone number in E.164 format, e.g.
                ``"+15551234567"``.  The number must start with ``+``
                followed by the country code.
            body: Text content of the SMS message.

        Returns:
            str: Confirmation string with the Commune SMS ID and status on
            success.  Returns an error message (beginning with ``"Error:"``)
            when the number is invalid or the API call fails.
        """
        if not to:
            return "Error: recipient phone number (to) cannot be empty."
        if not _validate_e164(to):
            return (
                f'Error: "{to}" is not a valid E.164 phone number. '
                "Use the format +<country_code><number>, e.g. +15551234567."
            )
        if not body:
            return "Error: SMS body cannot be empty."
        try:
            result = self._client.sms.send(to=to, body=body)
            msg_id = result.get("id", "unknown")
            status = result.get("status", "unknown")
            logger.debug(f"SMS sent: id={msg_id} status={status}")
            return f"SMS sent successfully. ID: {msg_id}, status: {status}."
        except Exception as e:
            logger.error(f"send_sms failed: {e}")
            return f"Error sending SMS: {e}"

    def read_sms(self, limit: int = 10) -> str:
        """Retrieve and display recent SMS messages.

        Use this tool to check incoming or recent SMS activity — for example
        to see replies from users, verify delivery of outbound messages, or
        process inbound texts as part of a support workflow.

        Args:
            limit: Maximum number of messages to return (default ``10``).

        Returns:
            str: A formatted, human-readable list of SMS messages showing
            direction (inbound/outbound), contact number, relative time, and
            the message body.  Returns ``"No SMS messages found."`` when
            there are no messages.

            Example output::

                [1] FROM: +15551234567 | 5m ago | Hi, I need help with my order
                [2] TO: +15559876543 | 1h ago | Your code is 482910
        """
        try:
            messages = self._client.sms.list(limit=limit)
            return _format_sms_list(messages)
        except Exception as e:
            logger.error(f"read_sms failed: {e}")
            return f"Error reading SMS messages: {e}"

    # ------------------------------------------------------------------
    # Credits / account
    # ------------------------------------------------------------------

    def get_credits(self) -> str:
        """Check the remaining Commune credit balance.

        Use this tool before starting a high-volume send operation to confirm
        there is sufficient credit, or any time you need to report the
        account's current balance.

        Returns:
            str: A human-readable balance string, e.g.
            ``"Credit balance: $42.50 USD"``.  Includes a low-balance
            warning when the balance is below $5.00.  Returns an error
            message on failure.
        """
        try:
            info = self._client.credits.get()
            balance = float(info.get("balance", 0))
            currency = info.get("currency", "USD")
            message = f"Credit balance: ${balance:.2f} {currency}."
            if balance < 5.0:
                message += (
                    f" Warning: balance is low (${balance:.2f}). "
                    "Top up to avoid send failures."
                )
            return message
        except Exception as e:
            logger.error(f"get_credits failed: {e}")
            return f"Error fetching credit balance: {e}"
