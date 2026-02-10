import json
from os import getenv
from typing import Any, Dict, List, Optional

import httpx

from agno.tools import Toolkit
from agno.utils.log import logger


class WhatsAppTools(Toolkit):
    def __init__(
        self,
        access_token: Optional[str] = None,
        phone_number_id: Optional[str] = None,
        version: Optional[str] = None,
        recipient_waid: Optional[str] = None,
        # Enable/disable flags
        enable_send_text_message: bool = True,
        enable_send_template_message: bool = True,
        enable_send_reply_buttons: bool = False,
        enable_send_list_message: bool = False,
        enable_send_image: bool = False,
        enable_send_document: bool = False,
        enable_send_location: bool = False,
        enable_send_reaction: bool = False,
        enable_mark_as_read: bool = False,
        all: bool = False,
        **kwargs,
    ):
        self.access_token = access_token or getenv("WHATSAPP_ACCESS_TOKEN")
        if not self.access_token:
            raise ValueError("WHATSAPP_ACCESS_TOKEN is not set. Set the environment variable or pass access_token.")

        self.phone_number_id = phone_number_id or getenv("WHATSAPP_PHONE_NUMBER_ID")
        if not self.phone_number_id:
            raise ValueError(
                "WHATSAPP_PHONE_NUMBER_ID is not set. Set the environment variable or pass phone_number_id."
            )

        self.default_recipient = recipient_waid or getenv("WHATSAPP_RECIPIENT_WAID")
        self.version = version or getenv("WHATSAPP_VERSION", "v22.0")
        self.base_url = "https://graph.facebook.com"

        tools: List[Any] = []
        if enable_send_text_message or all:
            tools.append(self.send_text_message)
        if enable_send_template_message or all:
            tools.append(self.send_template_message)
        if enable_send_reply_buttons or all:
            tools.append(self.send_reply_buttons)
        if enable_send_list_message or all:
            tools.append(self.send_list_message)
        if enable_send_image or all:
            tools.append(self.send_image)
        if enable_send_document or all:
            tools.append(self.send_document)
        if enable_send_location or all:
            tools.append(self.send_location)
        if enable_send_reaction or all:
            tools.append(self.send_reaction)
        if enable_mark_as_read or all:
            tools.append(self.mark_as_read)

        super().__init__(name="whatsapp", tools=tools, **kwargs)

    def _get_headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}", "Content-Type": "application/json"}

    def _get_messages_url(self) -> str:
        return f"{self.base_url}/{self.version}/{self.phone_number_id}/messages"

    def _resolve_recipient(self, recipient: Optional[str]) -> Optional[str]:
        if recipient:
            return recipient
        if self.default_recipient:
            return self.default_recipient
        return None

    def _send_message(self, data: Dict[str, Any]) -> Dict[str, Any]:
        response = httpx.post(self._get_messages_url(), headers=self._get_headers(), json=data)
        response.raise_for_status()
        return response.json()

    def send_text_message(
        self,
        text: str,
        recipient: Optional[str] = None,
        preview_url: bool = False,
    ) -> str:
        """Send a text message to a WhatsApp user.

        Args:
            text: The text message to send.
            recipient: Recipient's WhatsApp ID or phone number (e.g., "+1234567890"). Uses default if not provided.
            preview_url: Whether to show link previews.

        Returns:
            A JSON string with message ID or error.
        """
        try:
            to = self._resolve_recipient(recipient)
            if not to:
                return json.dumps({"error": "No recipient provided and no default recipient set"})

            data = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": to,
                "type": "text",
                "text": {"preview_url": preview_url, "body": text},
            }
            response = self._send_message(data)
            message_id = response.get("messages", [{}])[0].get("id", "unknown")
            return json.dumps({"ok": True, "message_id": message_id})
        except Exception as e:
            logger.error(f"Error sending text message: {e}")
            return json.dumps({"error": str(e)})

    def send_template_message(
        self,
        template_name: str,
        recipient: Optional[str] = None,
        language_code: str = "en_US",
        components: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """Send a template message to a WhatsApp user.

        Args:
            template_name: Name of the approved template.
            recipient: Recipient's WhatsApp ID or phone number. Uses default if not provided.
            language_code: Language code for the template (e.g., "en_US").
            components: Optional list of template components (header, body, buttons).

        Returns:
            A JSON string with message ID or error.
        """
        try:
            to = self._resolve_recipient(recipient)
            if not to:
                return json.dumps({"error": "No recipient provided and no default recipient set"})

            template: Dict[str, Any] = {"name": template_name, "language": {"code": language_code}}
            if components:
                template["components"] = components

            data = {
                "messaging_product": "whatsapp",
                "to": to,
                "type": "template",
                "template": template,
            }
            response = self._send_message(data)
            message_id = response.get("messages", [{}])[0].get("id", "unknown")
            return json.dumps({"ok": True, "message_id": message_id})
        except Exception as e:
            logger.error(f"Error sending template message: {e}")
            return json.dumps({"error": str(e)})

    def send_reply_buttons(
        self,
        body_text: str,
        buttons: List[Dict[str, str]],
        recipient: Optional[str] = None,
        header: Optional[str] = None,
        footer: Optional[str] = None,
    ) -> str:
        """Send an interactive reply button message to a WhatsApp user.

        Args:
            body_text: The message body text (max 1024 chars).
            buttons: List of button dicts, each with 'id' and 'title' keys. Max 3 buttons, title max 20 chars.
            recipient: Recipient phone number. Uses default if not provided.
            header: Optional header text.
            footer: Optional footer text.

        Returns:
            A JSON string with message ID or error.
        """
        try:
            to = self._resolve_recipient(recipient)
            if not to:
                return json.dumps({"error": "No recipient provided and no default recipient set"})

            if len(buttons) > 3:
                return json.dumps({"error": "WhatsApp allows a maximum of 3 reply buttons"})

            action_buttons = [{"type": "reply", "reply": {"id": btn["id"], "title": btn["title"]}} for btn in buttons]

            interactive: Dict[str, Any] = {
                "type": "button",
                "body": {"text": body_text},
                "action": {"buttons": action_buttons},
            }
            if header:
                interactive["header"] = {"type": "text", "text": header}
            if footer:
                interactive["footer"] = {"text": footer}

            data = {
                "messaging_product": "whatsapp",
                "to": to,
                "type": "interactive",
                "interactive": interactive,
            }
            response = self._send_message(data)
            message_id = response.get("messages", [{}])[0].get("id", "unknown")
            return json.dumps({"ok": True, "message_id": message_id})
        except Exception as e:
            logger.error(f"Error sending reply buttons: {e}")
            return json.dumps({"error": str(e)})

    def send_list_message(
        self,
        body_text: str,
        button_text: str,
        sections: List[Dict[str, Any]],
        recipient: Optional[str] = None,
        header: Optional[str] = None,
        footer: Optional[str] = None,
    ) -> str:
        """Send an interactive list message to a WhatsApp user.

        Args:
            body_text: The message body text.
            button_text: Text on the list button (max 20 chars).
            sections: List of section dicts with 'title' and 'rows'. Each row has 'id', 'title', optional 'description'.
            recipient: Recipient phone number. Uses default if not provided.
            header: Optional header text.
            footer: Optional footer text.

        Returns:
            A JSON string with message ID or error.
        """
        try:
            to = self._resolve_recipient(recipient)
            if not to:
                return json.dumps({"error": "No recipient provided and no default recipient set"})

            interactive: Dict[str, Any] = {
                "type": "list",
                "body": {"text": body_text},
                "action": {
                    "button": button_text,
                    "sections": sections,
                },
            }
            if header:
                interactive["header"] = {"type": "text", "text": header}
            if footer:
                interactive["footer"] = {"text": footer}

            data = {
                "messaging_product": "whatsapp",
                "to": to,
                "type": "interactive",
                "interactive": interactive,
            }
            response = self._send_message(data)
            message_id = response.get("messages", [{}])[0].get("id", "unknown")
            return json.dumps({"ok": True, "message_id": message_id})
        except Exception as e:
            logger.error(f"Error sending list message: {e}")
            return json.dumps({"error": str(e)})

    def send_image(
        self,
        recipient: Optional[str] = None,
        image_url: Optional[str] = None,
        media_id: Optional[str] = None,
        caption: Optional[str] = None,
    ) -> str:
        """Send an image to a WhatsApp user by URL or media ID.

        Args:
            recipient: Recipient phone number. Uses default if not provided.
            image_url: Public URL of the image. Provide either image_url or media_id.
            media_id: WhatsApp media ID from a previous upload. Provide either image_url or media_id.
            caption: Optional image caption.

        Returns:
            A JSON string with message ID or error.
        """
        try:
            to = self._resolve_recipient(recipient)
            if not to:
                return json.dumps({"error": "No recipient provided and no default recipient set"})

            if not image_url and not media_id:
                return json.dumps({"error": "Either image_url or media_id must be provided"})

            image: Dict[str, Any] = {}
            if media_id:
                image["id"] = media_id
            else:
                image["link"] = image_url
            if caption:
                image["caption"] = caption

            data = {
                "messaging_product": "whatsapp",
                "to": to,
                "type": "image",
                "image": image,
            }
            response = self._send_message(data)
            message_id = response.get("messages", [{}])[0].get("id", "unknown")
            return json.dumps({"ok": True, "message_id": message_id})
        except Exception as e:
            logger.error(f"Error sending image: {e}")
            return json.dumps({"error": str(e)})

    def send_document(
        self,
        recipient: Optional[str] = None,
        document_url: Optional[str] = None,
        media_id: Optional[str] = None,
        filename: Optional[str] = None,
        caption: Optional[str] = None,
    ) -> str:
        """Send a document to a WhatsApp user by URL or media ID.

        Args:
            recipient: Recipient phone number. Uses default if not provided.
            document_url: Public URL of the document. Provide either document_url or media_id.
            media_id: WhatsApp media ID from a previous upload. Provide either document_url or media_id.
            filename: Display filename for the document.
            caption: Optional document caption.

        Returns:
            A JSON string with message ID or error.
        """
        try:
            to = self._resolve_recipient(recipient)
            if not to:
                return json.dumps({"error": "No recipient provided and no default recipient set"})

            if not document_url and not media_id:
                return json.dumps({"error": "Either document_url or media_id must be provided"})

            document: Dict[str, Any] = {}
            if media_id:
                document["id"] = media_id
            else:
                document["link"] = document_url
            if filename:
                document["filename"] = filename
            if caption:
                document["caption"] = caption

            data = {
                "messaging_product": "whatsapp",
                "to": to,
                "type": "document",
                "document": document,
            }
            response = self._send_message(data)
            message_id = response.get("messages", [{}])[0].get("id", "unknown")
            return json.dumps({"ok": True, "message_id": message_id})
        except Exception as e:
            logger.error(f"Error sending document: {e}")
            return json.dumps({"error": str(e)})

    def send_location(
        self,
        latitude: str,
        longitude: str,
        name: Optional[str] = None,
        address: Optional[str] = None,
        recipient: Optional[str] = None,
    ) -> str:
        """Send a location pin to a WhatsApp user.

        Args:
            latitude: Latitude of the location.
            longitude: Longitude of the location.
            name: Optional name of the location.
            address: Optional address text.
            recipient: Recipient phone number. Uses default if not provided.

        Returns:
            A JSON string with message ID or error.
        """
        try:
            to = self._resolve_recipient(recipient)
            if not to:
                return json.dumps({"error": "No recipient provided and no default recipient set"})

            location: Dict[str, Any] = {
                "latitude": latitude,
                "longitude": longitude,
            }
            if name:
                location["name"] = name
            if address:
                location["address"] = address

            data = {
                "messaging_product": "whatsapp",
                "to": to,
                "type": "location",
                "location": location,
            }
            response = self._send_message(data)
            message_id = response.get("messages", [{}])[0].get("id", "unknown")
            return json.dumps({"ok": True, "message_id": message_id})
        except Exception as e:
            logger.error(f"Error sending location: {e}")
            return json.dumps({"error": str(e)})

    def send_reaction(
        self,
        message_id: str,
        emoji: str,
        recipient: Optional[str] = None,
    ) -> str:
        """React to a WhatsApp message with an emoji.

        Args:
            message_id: The wamid of the message to react to.
            emoji: The emoji to react with (e.g., thumbs up).
            recipient: Recipient phone number. Uses default if not provided.

        Returns:
            A JSON string with message ID or error.
        """
        try:
            to = self._resolve_recipient(recipient)
            if not to:
                return json.dumps({"error": "No recipient provided and no default recipient set"})

            data = {
                "messaging_product": "whatsapp",
                "to": to,
                "type": "reaction",
                "reaction": {
                    "message_id": message_id,
                    "emoji": emoji,
                },
            }
            response = self._send_message(data)
            resp_message_id = response.get("messages", [{}])[0].get("id", "unknown")
            return json.dumps({"ok": True, "message_id": resp_message_id})
        except Exception as e:
            logger.error(f"Error sending reaction: {e}")
            return json.dumps({"error": str(e)})

    def mark_as_read(self, message_id: str) -> str:
        """Send a read receipt for a WhatsApp message.

        Args:
            message_id: The wamid of the message to mark as read.

        Returns:
            A JSON string with success status or error.
        """
        try:
            data = {
                "messaging_product": "whatsapp",
                "status": "read",
                "message_id": message_id,
            }
            response = self._send_message(data)
            return json.dumps({"ok": True, "success": response.get("success", True)})
        except Exception as e:
            logger.error(f"Error marking message as read: {e}")
            return json.dumps({"error": str(e)})
