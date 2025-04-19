import base64
from pathlib import Path

import httpx


def download_image(url: str, output_path: str) -> bool:
    """
    Downloads an image from the specified URL and saves it to the given local path.
    Parameters:
    - url (str): URL of the image to download.
    - output_path (str): Local filesystem path to save the image
    """
    try:
        # Send HTTP GET request to the image URL
        response = httpx.get(url)
        response.raise_for_status()  # Raise an exception for HTTP errors

        # Check if the response contains image content
        content_type = response.headers.get("Content-Type")
        if not content_type or not content_type.startswith("image"):
            print(f"URL does not point to an image. Content-Type: {content_type}")
            return False

        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        # Write the image to the local file in binary mode
        with open(output_path, "wb") as file:
            for chunk in response.iter_bytes(chunk_size=8192):
                if chunk:
                    file.write(chunk)

        print(f"Image successfully downloaded and saved to '{output_path}'.")
        return True

    except httpx.HTTPError as e:
        print(f"Error downloading the image: {e}")
        return False
    except IOError as e:
        print(f"Error saving the image to '{output_path}': {e}")
        return False


def download_video(url: str, output_path: str) -> str:
    """Download video from URL"""
    response = httpx.get(url)
    response.raise_for_status()

    with open(output_path, "wb") as f:
        for chunk in response.iter_bytes(chunk_size=8192):
            f.write(chunk)
    return output_path


def download_file(url: str, output_path: str) -> None:
    """
    Download a file from a given URL and save it to the specified path.

    Args:
        url (str): The URL of the file to download
        output_path (str): The local path where the file should be saved

    Raises:
        httpx.HTTPError: If the download fails
    """
    try:
        response = httpx.get(url)
        response.raise_for_status()

        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        with open(output_file, "wb") as f:
            for chunk in response.iter_bytes(chunk_size=8192):
                if chunk:
                    f.write(chunk)

    except httpx.HTTPError as e:
        raise Exception(f"Failed to download file from {url}: {str(e)}")


def save_audio(base64_data: str, output_path: str) -> bool:
    """
    Saves base64 string to the specified path.
    """
    try:
        # Decode the base64 string into bytes
        decoded_data = base64.b64decode(base64_data)
    except Exception as e:
        raise Exception(f"An unexpected error occurred during base64 decoding: {e}")

    try:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        # Write the bytes to the local file in binary mode
        with open(path, "wb") as file:
            file.write(decoded_data)

        print(f"Data successfully saved to '{path}'.")
        return True
    except Exception as e:
        raise Exception(f"An unexpected error occurred while saving data to '{output_path}': {e}")
