import json
from os import getenv
from typing import Any, List, Optional

from agno.tools import Toolkit
from agno.utils.log import logger

try:
    from webexpythonsdk import WebexAPI
    from webexpythonsdk.exceptions import ApiError
except ImportError:
    logger.error("Webex tools require the `webexpythonsdk` package. Run `pip install webexpythonsdk` to install it.")


class WebexTools(Toolkit):
    def __init__(
        self,
        enable_send_message: bool = True,
        enable_list_rooms: bool = True,
        all: bool = False,
        access_token: Optional[str] = None,
        **kwargs,
    ):
        access_token = access_token or getenv("WEBEX_ACCESS_TOKEN")
        if access_token is None:
            raise ValueError("Webex access token is not set. Please set the WEBEX_ACCESS_TOKEN environment variable.")

        self.client = WebexAPI(access_token=access_token)

        tools: List[Any] = []
        if all or enable_send_message:
            tools.append(self.send_message)
        if all or enable_list_rooms:
            tools.append(self.list_rooms)

        super().__init__(name="webex", tools=tools, **kwargs)

    def send_message(self, room_id: str, text: str) -> str:
        """
        Send a message to a Webex Room.
        Args:
            room_id (str): The Room ID to send the message to.
            text (str): The text of the message to send.
        Returns:
            str: A JSON string containing the response from the Webex.
        """
        try:
            response = self.client.messages.create(roomId=room_id, text=text)
            return json.dumps(response.json_data)
        except ApiError as e:
            logger.error(f"Error sending message: {e} in room: {room_id}")
            return json.dumps({"error": str(e)})

    def list_rooms(self) -> str:
        """
        List all rooms in the Webex.
        Returns:
            str: A JSON string containing the list of rooms.
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
            logger.error(f"Error listing rooms: {e}")
            return json.dumps({"error": str(e)})
