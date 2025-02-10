from pathlib import Path

import requests


def download_image(url, save_path):
    """
    Downloads an image from the specified URL and saves it to the given local path.
    Parameters:
    - url (str): URL of the image to download.
    - save_path (str): Local filesystem path to save the image.
    """
    try:
        # Send HTTP GET request to the image URL
        response = requests.get(url, stream=True)
        response.raise_for_status()  # Raise an exception for HTTP errors

        # Check if the response contains image content
        content_type = response.headers.get("Content-Type")
        if not content_type or not content_type.startswith("image"):
            print(f"URL does not point to an image. Content-Type: {content_type}")
            return False

        path = Path(save_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        # Write the image to the local file in binary mode
        with open(save_path, "wb") as file:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    file.write(chunk)

        print(f"Image successfully downloaded and saved to '{save_path}'.")
        return True

    except requests.exceptions.RequestException as e:
        print(f"Error downloading the image: {e}")
        return False
    except IOError as e:
        print(f"Error saving the image to '{save_path}': {e}")
        return False


def download_video(url: str, output_path: str) -> str:
    """Download video from URL"""
    response = requests.get(url, stream=True)
    response.raise_for_status()

    with open(output_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)
    return output_path
