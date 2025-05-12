from dotenv import load_dotenv
import os
import requests

load_dotenv()

VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN")
ACCESS_TOKEN= os.getenv("WHATSAPP_ACCESS_TOKEN")


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
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}"
    }
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()  # Raise an HTTPError for bad responses (4xx and 5xx)
        data = response.json()
        
        # Extract a specific part of the response
        # Example: Extracting the "id" field
        media_url = data.get("url")
        #return extracted_part
    except requests.exceptions.RequestException as e:
        return {"error": str(e)}
    try:
        response = requests.get(media_url, headers=headers)
        response.raise_for_status()  # Raise an HTTPError for bad responses (4xx and 5xx)
        #type = response.headers['Content-Type']
        data= response.content
        return data
    except requests.exceptions.RequestException as e:
        return {"error": str(e)}
