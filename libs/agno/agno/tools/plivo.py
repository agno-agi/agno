import re
from os import getenv
from typing import Any, Dict, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_error, log_info, logger

try:
    import plivo
    from plivo.exceptions import PlivoRestError
except ImportError:
    raise ImportError("`plivo` not installed. Please install it using `pip install plivo`.")


class PlivoTools(Toolkit):
    def __init__(
        self,
        auth_id: Optional[str] = None,
        auth_token: Optional[str] = None,
        debug: bool = False,
        enable_send_sms: bool = True,
        enable_make_call: bool = True,
        enable_get_call_details: bool = True,
        enable_list_messages: bool = True,
        all: bool = False,
        **kwargs,
    ):
        """Initialize the Plivo toolkit.

        Authentication uses the Plivo Auth ID and Auth Token from the console
        (https://cx.plivo.com).

        Args:
            auth_id: Plivo Auth ID
            auth_token: Plivo Auth Token
            debug: Enable debug logging
            enable_send_sms: Register the send_sms tool
            enable_make_call: Register the make_call tool
            enable_get_call_details: Register the get_call_details tool
            enable_list_messages: Register the list_messages tool
            all: Register all tools regardless of the individual enable_* flags
        """
        self.auth_id = auth_id or getenv("PLIVO_AUTH_ID")
        self.auth_token = auth_token or getenv("PLIVO_AUTH_TOKEN")

        if not self.auth_id or not self.auth_token:
            log_error(
                "Plivo credentials not set. Please set the PLIVO_AUTH_ID and PLIVO_AUTH_TOKEN environment variables."
            )

        self.client = plivo.RestClient(auth_id=self.auth_id, auth_token=self.auth_token)

        if debug:
            import logging

            logging.basicConfig()
            logging.getLogger("plivo").setLevel(logging.DEBUG)

        tools: List[Any] = []
        if all or enable_send_sms:
            tools.append(self.send_sms)
        if all or enable_make_call:
            tools.append(self.make_call)
        if all or enable_get_call_details:
            tools.append(self.get_call_details)
        if all or enable_list_messages:
            tools.append(self.list_messages)

        super().__init__(name="plivo", tools=tools, **kwargs)

    @staticmethod
    def validate_phone_number(phone: str) -> bool:
        """Validate E.164 phone number format"""
        return bool(re.match(r"^\+[1-9]\d{1,14}$", phone))

    def send_sms(self, to: str, from_: str, body: str) -> str:
        """
        Send an SMS message using Plivo.

        Args:
            to: Recipient phone number (E.164 format). Single recipient only.
            from_: Sender ID — a Plivo number, short code, or alphanumeric sender ID
            body: Message content

        Returns:
            str: Message UUID if successful, error message if failed
        """
        try:
            if not self.validate_phone_number(to):
                return "Error: 'to' number must be in E.164 format (e.g., +1234567890)"
            if not from_ or len(from_.strip()) == 0:
                return "Error: Sender ID (from_) cannot be empty"
            if not body or len(body.strip()) == 0:
                return "Error: Message body cannot be empty"

            response = self.client.messages.create(src=from_, dst=to, text=body)
            message_uuid = response.message_uuid[0] if getattr(response, "message_uuid", None) else "unknown"
            log_info(f"SMS sent. UUID: {message_uuid}, to: {to}")
            return f"Message sent successfully. UUID: {message_uuid}"
        except PlivoRestError as e:
            logger.exception(f"Failed to send SMS to {to}")
            return f"Error sending message: {str(e)}"

    def make_call(self, to: str, from_: str, answer_url: str, answer_method: str = "POST") -> str:
        """
        Place an outbound call using Plivo.

        Args:
            to: Recipient phone number (E.164 format)
            from_: Caller ID — a Plivo voice-enabled number
            answer_url: URL Plivo requests when the call is answered; must return Plivo XML
            answer_method: HTTP method Plivo uses for the answer URL, GET or POST (default POST)

        Returns:
            str: Call request UUID if successful, error message if failed
        """
        try:
            if not self.validate_phone_number(to):
                return "Error: 'to' number must be in E.164 format (e.g., +1234567890)"
            if not from_ or len(from_.strip()) == 0:
                return "Error: Caller ID (from_) cannot be empty"
            if not answer_url or len(answer_url.strip()) == 0:
                return "Error: answer_url cannot be empty"
            method = answer_method.upper()
            if method not in ("GET", "POST"):
                return "Error: answer_method must be GET or POST"

            response = self.client.calls.create(from_=from_, to_=to, answer_url=answer_url, answer_method=method)
            request_uuid = getattr(response, "request_uuid", None) or "unknown"
            log_info(f"Call placed. request_uuid: {request_uuid}, to: {to}")
            return f"Call placed successfully. request_uuid: {request_uuid}"
        except PlivoRestError as e:
            logger.exception(f"Failed to place call to {to}")
            return f"Error placing call: {str(e)}"

    def get_call_details(self, call_uuid: str) -> Dict[str, Any]:
        """
        Get details about a specific call.

        Args:
            call_uuid: The UUID of the call to look up

        Returns:
            Dict: Call details including state, duration, etc.
        """
        try:
            call = self.client.calls.get(call_uuid)
            log_info(f"Fetched details for call UUID: {call_uuid}")
            return {
                "to": getattr(call, "to_number", None),
                "from": getattr(call, "from_number", None),
                "state": getattr(call, "call_state", None),
                "duration": getattr(call, "call_duration", None),
                "direction": getattr(call, "call_direction", None),
                "initiation_time": getattr(call, "initiation_time", None),
                "answer_time": getattr(call, "answer_time", None),
                "total_amount": getattr(call, "total_amount", None),
            }
        except PlivoRestError as e:
            logger.exception(f"Failed to fetch call details for UUID {call_uuid}")
            return {"error": str(e)}

    def list_messages(self, limit: int = 20) -> List[Dict[str, Any]]:
        """
        List recent messages.

        Args:
            limit: Maximum number of messages to return (capped at 20, the Plivo per-request maximum)

        Returns:
            List[Dict]: List of message details
        """
        try:
            limit = max(1, min(limit, 20))
            messages = []
            for message in self.client.messages.list(limit=limit):
                messages.append(
                    {
                        "message_uuid": getattr(message, "message_uuid", None),
                        "to": getattr(message, "to_number", None),
                        "from": getattr(message, "from_number", None),
                        "state": getattr(message, "message_state", None),
                        "direction": getattr(message, "message_direction", None),
                        "type": getattr(message, "message_type", None),
                        "message_time": getattr(message, "message_time", None),
                    }
                )
            log_info(f"Retrieved {len(messages)} messages")
            return messages
        except PlivoRestError as e:
            logger.exception("Failed to list messages")
            return [{"error": str(e)}]
