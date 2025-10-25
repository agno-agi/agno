import base64
import time
from enum import Enum
from pathlib import Path
from typing import List

import httpx

from agno.utils.log import log_info, log_warning


class SampleDataFileExtension(str, Enum):
    DOCX = "docx"
    PDF = "pdf"
    TXT = "txt"
    JSON = "json"
    CSV = "csv"


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
            log_warning(f"URL does not point to an image. Content-Type: {content_type}")
            return False

        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        # Write the image to the local file in binary mode
        with open(output_path, "wb") as file:
            for chunk in response.iter_bytes(chunk_size=8192):
                if chunk:
                    file.write(chunk)

        log_info(f"Image successfully downloaded and saved to '{output_path}'.")
        return True

    except httpx.HTTPError as e:
        log_warning(f"Error downloading the image: {e}")
        return False
    except IOError as e:
        log_warning(f"Error saving the image to '{output_path}': {e}")
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


def save_base64_data(base64_data: str, output_path: str) -> bool:
    """
    Saves base64 string to the specified path as bytes.
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

        log_info(f"Data successfully saved to '{path}'.")
        return True
    except Exception as e:
        raise Exception(f"An unexpected error occurred while saving data to '{output_path}': {e}")


def wait_for_media_ready(url: str, timeout: int = 120, interval: int = 5, verbose: bool = True) -> bool:
    """
    Wait for media to be ready at URL by polling with HEAD requests.

    Args:
        url (str): The URL to check for media availability
        timeout (int): Maximum time to wait in seconds (default: 120)
        interval (int): Seconds between each check (default: 5)
        verbose (bool): Whether to print progress messages (default: True)

    Returns:
        bool: True if media is ready, False if timeout reached
    """
    max_attempts = timeout // interval

    if verbose:
        log_info("Media generated! Waiting for upload to complete...")

    for attempt in range(max_attempts):
        try:
            response = httpx.head(url, timeout=10)
            response.raise_for_status()
            if verbose:
                log_info(f"Media ready: {url}")
            return True
        except httpx.HTTPError:
            pass

        if verbose and (attempt + 1) % 3 == 0:
            log_info(f"Still processing... ({(attempt + 1) * interval}s elapsed)")

        time.sleep(interval)

    if verbose:
        log_warning(f"Timeout waiting for media. Try this URL later: {url}")
    return False


def download_knowledge_filters_sample_data(
    num_files: int = 5, file_extension: SampleDataFileExtension = SampleDataFileExtension.DOCX
) -> List[str]:
    """
    Download sample data files with configurable file extension.

    Args:
        num_files (int): Number of files to download
        file_extension (SampleDataFileExtension): File extension type (DOCX, PDF, TXT, JSON)

    Returns:
        List[str]: List of paths to downloaded files
    """
    file_paths = []
    root_path = Path.cwd()

    for i in range(1, num_files + 1):
        if file_extension == SampleDataFileExtension.CSV:
            filename = f"filters_{i}.csv"
        else:
            filename = f"cv_{i}.{file_extension.value}"

        download_path = root_path / "cookbook" / "data" / filename
        download_path.parent.mkdir(parents=True, exist_ok=True)

        download_file(
            f"https://agno-public.s3.us-east-1.amazonaws.com/demo_data/filters/{filename}", str(download_path)
        )
        file_paths.append(str(download_path))
    return file_paths
