import os
from typing import Optional, Union

import httpx

from agno.tools import Toolkit
from agno.utils.log import logger


class TelegramTools(Toolkit):
    base_url = "https://api.telegram.org"

    def __init__(self, chat_id: Union[str, int], token: Optional[str] = None):
        super().__init__(name="telegram")

        self.token = token or os.getenv("TELEGRAM_TOKEN")
        if not self.token:
            logger.error("TELEGRAM_TOKEN not set. Please set the TELEGRAM_TOKEN environment variable.")

        self.chat_id = chat_id

        self.register(self.send_message)

    def _call_post_method(self, method, *args, **kwargs):
        return httpx.post(f"{self.base_url}/bot{self.token}/{method}", *args, **kwargs)

    def send_message(self, message: str) -> str:
        """This function sends a message to the chat ID.

        :param message: The message to send.
        :return: The response from the API.
        """
        logger.debug(f"Sending telegram message: {message}")
        response = self._call_post_method("sendMessage", json={"chat_id": self.chat_id, "text": message})
        try:
            response.raise_for_status()
            return response.text
        except httpx.HTTPStatusError as e:
            return f"An error occurred: {e}"
