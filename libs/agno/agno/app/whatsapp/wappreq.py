import os

import requests
from dotenv import load_dotenv

load_dotenv()

VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN")
ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN")
PHONE_NUMBER_ID= os.getenv("WHATSAPP_PHONE_NUMBER_ID")

def get_media(media_id):
    """
    Sends a GET request to the Facebook Graph API to retrieve media information.

    Args:
        media_id (str): The ID of the media to retrieve.
        access_token (str): The access token for authentication.

    Returns:
        dict: The JSON response from the API if successful, or an error message.
    """
    url = f"https://graph.facebook.com/v22.0/{media_id}"
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()  # Raise an HTTPError for bad responses (4xx and 5xx)
        data = response.json()

        # Extract a specific part of the response
        # Example: Extracting the "id" field
        media_url = data.get("url")
        # return extracted_part
    except requests.exceptions.RequestException as e:
        return {"error": str(e)}
    try:
        response = requests.get(media_url, headers=headers)
        response.raise_for_status()  # Raise an HTTPError for bad responses (4xx and 5xx)
        # type = response.headers['Content-Type']
        data = response.content
        return data
    except requests.exceptions.RequestException as e:
        return {"error": str(e)}
def send_media(file_path, mime_type):
    """
    Sends a POST request to the Facebook Graph API to upload media for WhatsApp.

    Args:
        file_path (str): The path to the file to be uploaded.
        mime_type (str): The MIME type of the file.

    Returns:
        str or dict: The media ID if successful, or an error message.
    """
    url = f"https://graph.facebook.com/v22.0/{PHONE_NUMBER_ID}/media"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}"
    }
    data = {
        "messaging_product": "whatsapp"
    }
    try:
        with open(file_path, "rb") as f:
            files = {
                "file": (os.path.basename(file_path), f, mime_type)
            }
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