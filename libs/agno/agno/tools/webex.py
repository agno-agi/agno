import json
from os import getenv
from typing import Callable, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_error, log_exception

try:
    from webexpythonsdk import WebexAPI
    from webexpythonsdk.exceptions import ApiError
except ImportError as e:
    log_error(
        f"Webex tools require the `webexpythonsdk` package. Run `pip install webexpythonsdk` to install it.: {str(e)}"
    )


class WebexTools(Toolkit):
    """Toolkit for interacting with Webex messaging and rooms.

    Args:
        access_token: Webex access token. Falls back to WEBEX_ACCESS_TOKEN env var.
        send_message: Enable send_message tool. Defaults to False (externally visible).
        list_rooms: Enable list_rooms tool. Defaults to True.
    """

    def __init__(
        self,
        access_token: Optional[str] = None,
        send_message: bool = False,
        list_rooms: bool = True,
        all: bool = False,
        **kwargs,
    ):
        access_token = access_token or getenv("WEBEX_ACCESS_TOKEN")
        if access_token is None:
            raise ValueError("Webex access token is not set. Please set the WEBEX_ACCESS_TOKEN environment variable.")

        self.client = WebexAPI(access_token=access_token)

        tools: List[Callable] = []
        if all or send_message:
            tools.append(self.send_webex_message)
        if all or list_rooms:
            tools.append(self.list_webex_rooms)

        super().__init__(name="webex", tools=tools, **kwargs)

    def send_webex_message(self, room_id: str, text: str) -> str:
        """Send a message to a Webex room.

        Args:
            room_id: The room ID to send the message to.
            text: The text of the message to send.

        Returns:
            JSON with the message response.
        """
        try:
            response = self.client.messages.create(roomId=room_id, text=text)
            return json.dumps(response.json_data)
        except ApiError as e:
            log_exception(f"Error sending message in room: {room_id}")
            return json.dumps({"error": str(e)})

    def list_webex_rooms(self) -> str:
        """List all rooms in Webex.

        Returns:
            JSON with the list of rooms.
        """
        try:
            response = self.client.rooms.list()
            rooms_list = [
                {
                    "id": room.id,
                    "title": room.title,
                    "type": room.type,
                    "isPublic": room.isPublic,
                    "isReadOnly": room.isReadOnly,
                }
                for room in response
            ]

            return json.dumps({"rooms": rooms_list}, indent=4)
        except ApiError as e:
            log_exception("Error listing rooms")
            return json.dumps({"error": str(e)})
