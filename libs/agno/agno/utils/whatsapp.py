import os
from typing import Optional, Union

import httpx
import requests

from agno.utils.log import log_debug, log_error


def get_access_token() -> str:
    access_token = os.getenv("WHATSAPP_ACCESS_TOKEN")
    if not access_token:
        raise ValueError("WHATSAPP_ACCESS_TOKEN is not set")
    return access_token


def get_phone_number_id() -> str:
    phone_number_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
    if not phone_number_id:
        raise ValueError("WHATSAPP_PHONE_NUMBER_ID is not set")
    return phone_number_id


def get_media(media_id: str) -> Union[dict, bytes]:
    """
    Sends a GET request to the Facebook Graph API to retrieve media information.

    Args:
        media_id (str): The ID of the media to retrieve.
    """
    url = f"https://graph.facebook.com/v22.0/{media_id}"

    access_token = get_access_token()

    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()  # Raise an HTTPError for bad responses (4xx and 5xx)
        data = response.json()

        media_url = data.get("url")
    except requests.exceptions.RequestException as e:
        return {"error": str(e)}

    try:
        response = requests.get(media_url, headers=headers)
        response.raise_for_status()  # Raise an HTTPError for bad responses (4xx and 5xx)
        data = response.content
        return data
    except requests.exceptions.RequestException as e:
        return {"error": str(e)}


async def get_media_async(media_id: str) -> Union[dict, bytes]:
    """
    Sends a GET request to the Facebook Graph API to retrieve media information.

    Args:
        media_id (str): The ID of the media to retrieve.
    """
    url = f"https://graph.facebook.com/v22.0/{media_id}"

    access_token = get_access_token()

    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()  # Raise an HTTPError for bad responses (4xx and 5xx)
            data = response.json()

        media_url = data.get("url")
    except httpx.HTTPStatusError as e:
        return {"error": str(e)}

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(media_url, headers=headers)
            response.raise_for_status()  # Raise an HTTPError for bad responses (4xx and 5xx)
            data = response.content
        return data
    except httpx.HTTPStatusError as e:
        return {"error": str(e)}


def upload_media(media_data: bytes, mime_type: str, filename: str = "file"):
    """
    Sends a POST request to the Facebook Graph API to upload media for WhatsApp.

    Args:
        media_data: Bytes buffer containing the file data
        mime_type (str): The MIME type of the file
        filename (str): The name to use for the file in the upload. Defaults to "file"
    """
    phone_number_id = get_phone_number_id()

    url = f"https://graph.facebook.com/v22.0/{phone_number_id}/media"

    access_token = get_access_token()

    headers = {"Authorization": f"Bearer {access_token}"}

    data = {"messaging_product": "whatsapp", "type": mime_type}
    try:
        from io import BytesIO

        file_data = BytesIO(media_data)
        files = {"file": (filename, file_data, mime_type)}

        response = requests.post(url, headers=headers, data=data, files=files)
        response.raise_for_status()  # Raise an error for bad responses
        json_resp = response.json()
        media_id = json_resp.get("id")
        if not media_id:
            return {"error": "Media ID not found in response", "response": json_resp}
        return media_id
    except requests.exceptions.RequestException as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": str(e)}


async def upload_media_async(media_data: bytes, mime_type: str, filename: str = "file"):
    """
    Sends a POST request to the Facebook Graph API to upload media for WhatsApp.

    Args:
        media_data: Bytes buffer containing the file data
        mime_type (str): The MIME type of the file
        filename (str): The name to use for the file in the upload. Defaults to "file"
    """
    phone_number_id = get_phone_number_id()

    url = f"https://graph.facebook.com/v22.0/{phone_number_id}/media"

    access_token = get_access_token()

    headers = {"Authorization": f"Bearer {access_token}"}

    data = {"messaging_product": "whatsapp", "type": mime_type}
    try:
        from io import BytesIO

        file_data = BytesIO(media_data)
        files = {"file": (filename, file_data, mime_type)}

        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, data=data, files=files)
            response.raise_for_status()  # Raise an error for bad responses
            json_resp = response.json()
            media_id = json_resp.get("id")
            if not media_id:
                return {"error": "Media ID not found in response", "response": json_resp}
            return media_id
    except httpx.HTTPStatusError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": str(e)}


async def send_image_message_async(
    media_id: str,
    recipient: str,
    text: Optional[str] = None,
):
    """Send an image message to a WhatsApp user (asynchronous version).

    Args:
        media_id: The media id for the image to send
        recipient: Recipient's WhatsApp ID or phone number (e.g., "+1234567890").
        text: Caption for the image

    Returns:
        Success message with message ID
    """
    log_debug(f"Sending WhatsApp image to {recipient}: {text}")
    phone_number_id = get_phone_number_id()

    url = f"https://graph.facebook.com/v22.0/{phone_number_id}/messages"

    access_token = get_access_token()

    headers = {"Authorization": f"Bearer {access_token}"}

    data = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": recipient,
        "type": "image",
        "image": {"id": media_id, "caption": text},
    }

    try:
        async with httpx.AsyncClient() as client:
            import json

            log_debug(f"Request data: {json.dumps(data, indent=2)}")
            response = await client.post(url, headers=headers, json=data)
            response.raise_for_status()
            log_debug(f"Response: {response.text}")

    except httpx.HTTPStatusError as e:
        log_error(f"Failed to send WhatsApp image message: {e}")
        log_error(f"Error response: {e.response.text if hasattr(e, 'response') else 'No response text'}")
        raise
    except Exception as e:
        log_error(f"Unexpected error sending WhatsApp image message: {str(e)}")
        raise


def send_image_message(
    media_id: str,
    recipient: str,
    text: Optional[str] = None,
):
    """Send an image message to a WhatsApp user (synchronous version).

    Args:
        image: The media id for the image to send
        recipient: Recipient's WhatsApp ID or phone number (e.g., "+1234567890").
        text: Caption for the image

    Returns:
        Success message with message ID
    """
    log_debug(f"Sending WhatsApp image to {recipient}: {text}")
    phone_number_id = get_phone_number_id()

    url = f"https://graph.facebook.com/v22.0/{phone_number_id}/messages"

    access_token = get_access_token()

    headers = {"Authorization": f"Bearer {access_token}"}

    data = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": recipient,
        "type": "image",
        "image": {"id": media_id, "caption": text},
    }

    try:
        import json

        log_debug(f"Request data: {json.dumps(data, indent=2)}")
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        log_debug(f"Response: {response.text}")
    except requests.exceptions.RequestException as e:
        log_error(f"Failed to send WhatsApp image message: {e}")
        log_error(f"Error response: {e.response.text if hasattr(e, 'response') else 'No response text'}")  # type: ignore
        raise
    except Exception as e:
        log_error(f"Unexpected error sending WhatsApp image message: {str(e)}")
        raise


def typing_indicator(message_id: Optional[str] = None):
    if not message_id:
        return

    phone_number_id = get_phone_number_id()

    url = f"https://graph.facebook.com/v22.0/{phone_number_id}/messages"

    access_token = get_access_token()

    headers = {"Authorization": f"Bearer {access_token}"}
    data = {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": f"{message_id}",
        "typing_indicator": {"type": "text"},
    }
    try:
        response = requests.post(url, headers=headers, data=data)
        response.raise_for_status()  # Raise an HTTPError for bad responses (4xx and 5xx)
    except requests.exceptions.RequestException as e:
        return {"error": str(e)}


async def typing_indicator_async(message_id: Optional[str] = None):
    if not message_id:
        return

    phone_number_id = get_phone_number_id()

    url = f"https://graph.facebook.com/v22.0/{phone_number_id}/messages"

    access_token = get_access_token()

    headers = {"Authorization": f"Bearer {access_token}"}
    data = {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": f"{message_id}",
        "typing_indicator": {"type": "text"},
    }
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, data=data)
            response.raise_for_status()  # Raise an HTTPError for bad responses (4xx and 5xx)
    except httpx.HTTPStatusError as e:
        return {"error": str(e)}
