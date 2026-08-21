import json
import re
from os import getenv
from typing import Callable, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_error, log_exception, log_info

try:
    from twilio.base.exceptions import TwilioRestException
    from twilio.rest import Client
except ImportError:
    raise ImportError("`twilio` not installed. Please install it using `pip install twilio`.")


class TwilioTools(Toolkit):
    def __init__(
        self,
        account_sid: Optional[str] = None,
        auth_token: Optional[str] = None,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        region: Optional[str] = None,
        edge: Optional[str] = None,
        debug: bool = False,
        send_sms: bool = False,
        get_call_details: bool = True,
        list_messages: bool = True,
        all: bool = False,
        **kwargs,
    ):
        """Initialize the Twilio toolkit.

        Two authentication methods are supported:
        1. Account SID + Auth Token
        2. Account SID + API Key + API Secret

        Args:
            account_sid: Twilio Account SID. Falls back to TWILIO_ACCOUNT_SID env var.
            auth_token: Twilio Auth Token for Method 1. Falls back to TWILIO_AUTH_TOKEN env var.
            api_key: Twilio API Key for Method 2. Falls back to TWILIO_API_KEY env var.
            api_secret: Twilio API Secret for Method 2. Falls back to TWILIO_API_SECRET env var.
            region: Twilio region (e.g. 'au1'). Falls back to TWILIO_REGION env var.
            edge: Twilio edge location (e.g. 'sydney'). Falls back to TWILIO_EDGE env var.
            debug: Enable debug logging.
            send_sms: Enable send_sms tool. Default False (externally visible).
            get_call_details: Enable get_call_details tool. Default True.
            list_messages: Enable list_messages tool. Default True.
            all: Enable all tools.
        """
        # Backwards compat: enable_X -> X
        if "enable_send_sms" in kwargs:
            send_sms = kwargs.pop("enable_send_sms")
        if "enable_get_call_details" in kwargs:
            get_call_details = kwargs.pop("enable_get_call_details")
        if "enable_list_messages" in kwargs:
            list_messages = kwargs.pop("enable_list_messages")

        # Get credentials from environment if not provided
        self.account_sid = account_sid or getenv("TWILIO_ACCOUNT_SID")
        self.auth_token = auth_token or getenv("TWILIO_AUTH_TOKEN")
        self.api_key = api_key or getenv("TWILIO_API_KEY")
        self.api_secret = api_secret or getenv("TWILIO_API_SECRET")

        # Optional region and edge
        self.region = region or getenv("TWILIO_REGION")
        self.edge = edge or getenv("TWILIO_EDGE")

        # Validate required credentials
        if not self.account_sid:
            log_error("TWILIO_ACCOUNT_SID not set. Please set the TWILIO_ACCOUNT_SID environment variable.")

        # Initialize client based on provided authentication method
        if self.api_key and self.api_secret:
            # Method 2: API Key + Secret
            self.client = Client(
                self.api_key,
                self.api_secret,
                self.account_sid,
                region=self.region or None,
                edge=self.edge or None,
            )
        elif self.auth_token:
            # Method 1: Auth Token
            self.client = Client(
                self.account_sid,
                self.auth_token,
                region=self.region or None,
                edge=self.edge or None,
            )
        else:
            log_error(
                "Neither (auth_token) nor (api_key and api_secret) provided. "
                "Please set either TWILIO_AUTH_TOKEN or both TWILIO_API_KEY and TWILIO_API_SECRET environment variables."
            )

        if debug:
            import logging

            logging.basicConfig()
            self.client.http_client.logger.setLevel(logging.INFO)

        tools: List[Callable] = []
        if all or send_sms:
            tools.append(self.send_sms)
        if all or get_call_details:
            tools.append(self.get_call_details)
        if all or list_messages:
            tools.append(self.list_messages)

        super().__init__(name="twilio", tools=tools, **kwargs)

    @staticmethod
    def validate_phone_number(phone: str) -> bool:
        """Validate E.164 phone number format"""
        return bool(re.match(r"^\+[1-9]\d{1,14}$", phone))

    def send_sms(self, to: str, from_: str, body: str) -> str:
        """
        Send an SMS message using Twilio.

        Args:
            to: Recipient phone number (E.164 format)
            from_: Sender phone number (must be a Twilio number)
            body: Message content

        Returns:
            str: Message SID if successful, error message if failed
        """
        try:
            if not self.validate_phone_number(to):
                return json.dumps({"error": "'to' number must be in E.164 format (e.g., +1234567890)"})
            if not self.validate_phone_number(from_):
                return json.dumps({"error": "'from_' number must be in E.164 format (e.g., +1234567890)"})
            if not body or len(body.strip()) == 0:
                return json.dumps({"error": "Message body cannot be empty"})

            message = self.client.messages.create(to=to, from_=from_, body=body)
            log_info(f"SMS sent. SID: {message.sid}, to: {to}")
            return json.dumps({"ok": True, "message": "Message sent successfully", "sid": message.sid})
        except TwilioRestException as e:
            log_exception(f"Failed to send SMS to {to}")
            return json.dumps({"error": f"Error sending message: {str(e)}"})

    def get_call_details(self, call_sid: str) -> str:
        """
        Get details about a specific call.

        Args:
            call_sid: The SID of the call to lookup

        Returns:
            str: JSON string with call details including status, duration, etc.
        """
        try:
            call = self.client.calls(call_sid).fetch()
            log_info(f"Fetched details for call SID: {call_sid}")
            return json.dumps(
                {
                    "to": call.to,
                    "from": call.from_,
                    "status": call.status,
                    "duration": call.duration,
                    "direction": call.direction,
                    "price": call.price,
                    "start_time": str(call.start_time),
                    "end_time": str(call.end_time),
                }
            )
        except TwilioRestException as e:
            log_exception(f"Failed to fetch call details for SID {call_sid}")
            return json.dumps({"error": str(e)})

    def list_messages(self, limit: int = 20) -> str:
        """
        List recent SMS messages.

        Args:
            limit: Maximum number of messages to return

        Returns:
            str: JSON string with list of message details
        """
        try:
            messages = []
            for message in self.client.messages.list(limit=limit):
                messages.append(
                    {
                        "sid": message.sid,
                        "to": message.to,
                        "from": message.from_,
                        "body": message.body,
                        "status": message.status,
                        "date_sent": str(message.date_sent),
                    }
                )
            log_info(f"Retrieved {len(messages)} messages")
            return json.dumps({"messages": messages})
        except TwilioRestException as e:
            log_exception("Failed to list messages")
            return json.dumps({"error": str(e)})
