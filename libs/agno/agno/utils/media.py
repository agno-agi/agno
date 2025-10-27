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


def reconstruct_image_from_dict(img_data):
    """
    Reconstruct an Image object from dictionary data.

    Handles both base64-encoded content (from database) and regular image data (url/filepath).
    """
    from agno.media import Image

    if isinstance(img_data, dict):
        # If content is base64 string, decode it back to bytes
        if "content" in img_data and isinstance(img_data["content"], str):
            return Image.from_base64(
                img_data["content"],
                id=img_data.get("id"),
                mime_type=img_data.get("mime_type"),
                format=img_data.get("format"),
                detail=img_data.get("detail"),
                original_prompt=img_data.get("original_prompt"),
                revised_prompt=img_data.get("revised_prompt"),
                alt_text=img_data.get("alt_text"),
            )
        else:
            # Regular image (filepath/url)
            return Image(**img_data)
    return img_data


def reconstruct_video_from_dict(vid_data):
    """
    Reconstruct a Video object from dictionary data.

    Handles both base64-encoded content (from database) and regular video data (url/filepath).
    """
    from agno.media import Video

    if isinstance(vid_data, dict):
        # If content is base64 string, decode it back to bytes
        if "content" in vid_data and isinstance(vid_data["content"], str):
            return Video.from_base64(
                vid_data["content"],
                id=vid_data.get("id"),
                mime_type=vid_data.get("mime_type"),
                format=vid_data.get("format"),
            )
        else:
            # Regular video (filepath/url)
            return Video(**vid_data)
    return vid_data


def reconstruct_audio_from_dict(aud_data):
    """
    Reconstruct an Audio object from dictionary data.

    Handles both base64-encoded content (from database) and regular audio data (url/filepath).
    """
    from agno.media import Audio

    if isinstance(aud_data, dict):
        # If content is base64 string, decode it back to bytes
        if "content" in aud_data and isinstance(aud_data["content"], str):
            return Audio.from_base64(
                aud_data["content"],
                id=aud_data.get("id"),
                mime_type=aud_data.get("mime_type"),
                transcript=aud_data.get("transcript"),
                expires_at=aud_data.get("expires_at"),
                sample_rate=aud_data.get("sample_rate", 24000),
                channels=aud_data.get("channels", 1),
            )
        else:
            # Regular audio (filepath/url)
            return Audio(**aud_data)
    return aud_data


def reconstruct_file_from_dict(file_data):
    """
    Reconstruct a File object from dictionary data.

    Handles both base64-encoded content (from database) and regular file data (url/filepath).
    """
    from agno.media import File

    if isinstance(file_data, dict):
        # If content is base64 string, decode it back to bytes
        if "content" in file_data and isinstance(file_data["content"], str):
            return File.from_base64(
                file_data["content"],
                id=file_data.get("id"),
                mime_type=file_data.get("mime_type"),
                filename=file_data.get("filename"),
                name=file_data.get("name"),
                format=file_data.get("format"),
            )
        else:
            # Regular file (filepath/url)
            return File(**file_data)
    return file_data


def reconstruct_images(images_data):
    """Reconstruct a list of Image objects from list of dictionaries."""
    if not images_data:
        return None
    return [reconstruct_image_from_dict(img_data) for img_data in images_data]


def reconstruct_videos(videos_data):
    """Reconstruct a list of Video objects from list of dictionaries."""
    if not videos_data:
        return None
    return [reconstruct_video_from_dict(vid_data) for vid_data in videos_data]


def reconstruct_audio_list(audio_data):
    """Reconstruct a list of Audio objects from list of dictionaries."""
    if not audio_data:
        return None
    return [reconstruct_audio_from_dict(aud_data) for aud_data in audio_data]


def reconstruct_files(files_data):
    """Reconstruct a list of File objects from list of dictionaries."""
    if not files_data:
        return None
    return [reconstruct_file_from_dict(file_data) for file_data in files_data]


def reconstruct_response_audio(audio_data):
    """Reconstruct a single Audio object for response audio."""
    if not audio_data:
        return None
    return reconstruct_audio_from_dict(audio_data)
