import json

from agno.tools.toolkit import Toolkit
from agno.utils.log import logger

try:
    from webexpythonsdk import WebexAPI
    from webexpythonsdk.exceptions import ApiError
except ImportError:
    logger.error("Webex tools require the `webexpythonsdk` package. Run `pip install webexpythonsdk` to install it and you can set the access token through WEBEX_TEAMS_ACCESS_TOKEN")

class WebexTools(Toolkit):
    def __init__(self, token: str, send_message: bool = True, list_rooms: bool = True):
        super().__init__(name="webex")
        self.client = WebexAPI(access_token=token)
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
        
    @staticmethod
    def get_tool_name() -> str:
        """Returns the tool name"""
        return "webex"
