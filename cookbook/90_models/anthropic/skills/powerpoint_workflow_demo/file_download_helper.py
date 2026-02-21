import os
import re
from typing import List


def detect_file_extension(file_content: bytes) -> str:
    """
    Detect file type from magic bytes (file header).

    Args:
        file_content: First few bytes of the file

    Returns:
        File extension including dot (e.g., '.xlsx', '.docx', '.pptx')
    """
    # Check magic bytes for common Office file formats
    if file_content.startswith(b"PK\x03\x04"):
        # ZIP-based formats (Office 2007+)
        if b"word/" in file_content[:2000]:
            return ".docx"
        elif b"xl/" in file_content[:2000]:
            return ".xlsx"
        elif b"ppt/" in file_content[:2000]:
            return ".pptx"
        else:
            return ".zip"
    elif file_content.startswith(b"%PDF"):
        return ".pdf"
    elif file_content.startswith(b"\xd0\xcf\x11\xe0"):
        # Old Office format (97-2003)
        return ".doc"
    else:
        return ".bin"


def download_skill_files(
    response, client, output_dir: str = ".", default_filename: str = None
) -> List[str]:
    """
    Download files created by Claude Agent Skills from the API response.

    Args:
        response: The Anthropic API response object OR a dict with 'file_ids' key
        client: Anthropic client instance
        output_dir: Directory to save files (default: current directory)
        default_filename: Default filename to use

    Returns:
        List of downloaded file paths
    """
    downloaded_files = []
    seen_file_ids = set()

    # Check if response is a dict with file_ids (from provider_data)
    if isinstance(response, dict) and "file_ids" in response:
        for file_id in response["file_ids"]:
            if file_id in seen_file_ids:
                continue
            seen_file_ids.add(file_id)

            print(f"Found file ID: {file_id}")

            try:
                # Download the file
                file_content = client.beta.files.download(
                    file_id=file_id, betas=["files-api-2025-04-14"]
                )

                # Read file content
                file_data = file_content.read()

                # Detect actual file type from content
                detected_ext = detect_file_extension(file_data)

                # Use default filename or generate one
                filename = (
                    default_filename
                    if default_filename
                    else f"skill_output_{file_id[-8:]}{detected_ext}"
                )
                filepath = os.path.join(output_dir, filename)

                # Save to disk
                with open(filepath, "wb") as f:
                    f.write(file_data)

                downloaded_files.append(filepath)
                print(f"Downloaded: {filepath}")

            except Exception as e:
                print(f"Failed to download file {file_id}: {e}")

        return downloaded_files

    # Original logic: Iterate through response content blocks
    if not hasattr(response, "content"):
        return downloaded_files

    for block in response.content:
        if block.type == "bash_code_execution_tool_result":
            if hasattr(block, "content") and hasattr(block.content, "content"):
                if isinstance(block.content.content, list):
                    for output_block in block.content.content:
                        if hasattr(output_block, "file_id"):
                            file_id = output_block.file_id

                            if file_id in seen_file_ids:
                                continue
                            seen_file_ids.add(file_id)

                            print(f"Found file ID: {file_id}")

                            try:
                                file_content = client.beta.files.download(
                                    file_id=file_id, betas=["files-api-2025-04-14"]
                                )

                                file_data = file_content.read()
                                detected_ext = detect_file_extension(file_data)

                                filename = default_filename

                                if (
                                    not filename
                                    and hasattr(block.content, "stdout")
                                    and block.content.stdout
                                ):
                                    match = re.search(
                                        r"[\w\-]+\.(pptx|xlsx|docx|pdf)",
                                        block.content.stdout,
                                    )
                                    if match:
                                        extracted_filename = match.group(0)
                                        extracted_ext = os.path.splitext(
                                            extracted_filename
                                        )[1]
                                        if extracted_ext == detected_ext:
                                            filename = extracted_filename
                                        else:
                                            basename = os.path.splitext(
                                                extracted_filename
                                            )[0]
                                            filename = f"{basename}{detected_ext}"

                                if not filename:
                                    filename = (
                                        f"skill_output_{file_id[-8:]}{detected_ext}"
                                    )

                                filepath = os.path.join(output_dir, filename)

                                with open(filepath, "wb") as f:
                                    f.write(file_data)

                                downloaded_files.append(filepath)
                                print(f"Downloaded: {filepath}")

                            except Exception as e:
                                print(f"Failed to download file {file_id}: {e}")

    return downloaded_files
