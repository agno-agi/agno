import json
import os
from typing import Optional

from agno.tools.toolkit import Toolkit
from agno.utils.log import logger

try:
    from webexpythonsdk import WebexAPI
    from webexpythonsdk.exceptions import ApiError
except ImportError:
    logger.error("Webex tools require the `webexpythonsdk` package. Run `pip install webexpythonsdk` to install it.")


class WebexTools(Toolkit):
    def __init__(
        self, send_message: bool = True, list_rooms: bool = True, access_token: Optional[str] = None, **kwargs
    ):
        super().__init__(name="webex", **kwargs)
        if access_token is None:
            access_token = os.getenv("WEBEX_ACCESS_TOKEN")
        if access_token is None:
            raise ValueError("Webex access token is not set. Please set the WEBEX_ACCESS_TOKEN environment variable.")

        self.client = WebexAPI(access_token=access_token)
        if send_message:
            self.register(self.send_message)
        if list_rooms:
            self.register(self.list_rooms)

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
