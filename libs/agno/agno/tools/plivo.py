import re
from os import getenv
from typing import Any, Dict, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_error, log_info

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
        enable_list_calls: bool = True,
        enable_lookup_number: bool = True,
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
            enable_list_calls: Register the list_calls tool
            enable_lookup_number: Register the lookup_number tool
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
        if all or enable_list_calls:
            tools.append(self.list_calls)
        if all or enable_lookup_number:
            tools.append(self.lookup_number)

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
            log_error(f"Failed to send SMS to {to}")
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
            log_error(f"Failed to place call to {to}")
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
            log_error(f"Failed to fetch call details for UUID {call_uuid}")
            return {"error": str(e)}

    def list_messages(
        self, limit: int = 20, offset: int = 0, message_direction: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        List recent messages.

        Args:
            limit: Maximum number of messages to return (capped at 20, the Plivo per-request maximum)
            offset: Number of messages to skip, for paging past the per-request cap
            message_direction: Filter by direction, 'inbound' or 'outbound' (default all)

        Returns:
            List[Dict]: List of message details
        """
        try:
            limit = max(1, min(limit, 20))
            offset = max(0, offset)
            if message_direction is not None:
                message_direction = message_direction.strip() or None
            if message_direction is not None and message_direction not in ("inbound", "outbound"):
                return [{"error": "message_direction must be 'inbound' or 'outbound'"}]
            messages = []
            for message in self.client.messages.list(limit=limit, offset=offset, message_direction=message_direction):
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
            log_error("Failed to list messages")
            return [{"error": str(e)}]

    def list_calls(
        self, limit: int = 20, offset: int = 0, call_direction: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        List recent calls.

        Args:
            limit: Maximum number of calls to return (capped at 20, the Plivo per-request maximum)
            offset: Number of calls to skip, for paging past the per-request cap
            call_direction: Filter by direction, 'inbound' or 'outbound' (default all)

        Returns:
            List[Dict]: List of call details
        """
        try:
            limit = max(1, min(limit, 20))
            offset = max(0, offset)
            if call_direction is not None:
                call_direction = call_direction.strip() or None
            if call_direction is not None and call_direction not in ("inbound", "outbound"):
                return [{"error": "call_direction must be 'inbound' or 'outbound'"}]
            calls = []
            for call in self.client.calls.list(limit=limit, offset=offset, call_direction=call_direction):
                calls.append(
                    {
                        "call_uuid": getattr(call, "call_uuid", None),
                        "to": getattr(call, "to_number", None),
                        "from": getattr(call, "from_number", None),
                        "state": getattr(call, "call_state", None),
                        "duration": getattr(call, "call_duration", None),
                        "direction": getattr(call, "call_direction", None),
                        "end_time": getattr(call, "end_time", None),
                    }
                )
            log_info(f"Retrieved {len(calls)} calls")
            return calls
        except PlivoRestError as e:
            log_error("Failed to list calls")
            return [{"error": str(e)}]

    def lookup_number(self, number: str) -> Dict[str, Any]:
        """
        Look up carrier and line-type information for a phone number.

        Args:
            number: Phone number to look up (E.164 format)

        Returns:
            Dict: Number metadata including country, carrier, and line type, or error message
        """
        try:
            if not self.validate_phone_number(number):
                return {"error": "'number' must be in E.164 format (e.g., +1234567890)"}

            result = self.client.lookup.get(number)
            log_info(f"Looked up number: {number}")
            return {
                "number": getattr(result, "phone_number", None),
                "country": getattr(result, "country", None),
                "format": getattr(result, "format", None),
                "carrier": getattr(result, "carrier", None),
            }
        except PlivoRestError as e:
            log_error(f"Failed to look up number {number}")
            return {"error": str(e)}
