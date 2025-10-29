"""
File Download Helper for Claude Agent Skills.

Utility functions to download files created by Claude Agent Skills.
"""

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
        return ".doc"  # Could also be .xls or .ppt, default to .doc
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
        default_filename: Default filename to use (will infer from content if not provided)

    Returns:
        List of downloaded file paths

    Example:
        >>> from anthropic import Anthropic
        >>> client = Anthropic()
        >>> response = client.beta.messages.create(...)
        >>> files = download_skill_files(response, client)
        >>> print(f"Downloaded: {files}")

        >>> # Or with provider_data dict
        >>> provider_data = {"file_ids": ["file_123", "file_456"]}
        >>> files = download_skill_files(provider_data, client)
    """
    downloaded_files = []
    seen_file_ids = set()  # Track file IDs to avoid duplicates

    import os
    import re

    # Check if response is a dict with file_ids (from provider_data)
    if isinstance(response, dict) and "file_ids" in response:
        # Simple case: just download the file IDs
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
        # Check for bash_code_execution_tool_result blocks (Skills API format)
        if block.type == "bash_code_execution_tool_result":
            if hasattr(block, "content") and hasattr(block.content, "content"):
                # block.content is a BetaBashCodeExecutionResultBlock
                # block.content.content is a list of BetaBashCodeExecutionOutputBlock objects
                if isinstance(block.content.content, list):
                    for output_block in block.content.content:
                        if hasattr(output_block, "file_id"):
                            file_id = output_block.file_id

                            # Skip if we've already downloaded this file
                            if file_id in seen_file_ids:
                                continue
                            seen_file_ids.add(file_id)

                            print(f"📄 Found file ID: {file_id}")

                            try:
                                # Download the file
                                file_content = client.beta.files.download(
                                    file_id=file_id, betas=["files-api-2025-04-14"]
                                )

                                # Read file content - the response object is already bytes-like
                                file_data = file_content.read()

                                # Detect actual file type from content
                                detected_ext = detect_file_extension(file_data)

                                # Get filename from various sources
                                filename = default_filename

                                if (
                                    not filename
                                    and hasattr(block.content, "stdout")
                                    and block.content.stdout
                                ):
                                    # Try to extract filename from stdout (e.g., "test.pptx")
                                    match = re.search(
                                        r"[\w\-]+\.(pptx|xlsx|docx|pdf)",
                                        block.content.stdout,
                                    )
                                    if match:
                                        extracted_filename = match.group(0)
                                        # Verify the extension matches the actual file type
                                        extracted_ext = os.path.splitext(
                                            extracted_filename
                                        )[1]
                                        if extracted_ext == detected_ext:
                                            filename = extracted_filename
                                        else:
                                            # Use the basename but with correct extension
                                            basename = os.path.splitext(
                                                extracted_filename
                                            )[0]
                                            filename = f"{basename}{detected_ext}"

                                # If still no filename, use file ID with detected extension
                                if not filename:
                                    filename = (
                                        f"skill_output_{file_id[-8:]}{detected_ext}"
                                    )

                                filepath = os.path.join(output_dir, filename)

                                # Save to disk
                                with open(filepath, "wb") as f:
                                    f.write(file_data)

                                downloaded_files.append(filepath)
                                print(f"✅ Downloaded: {filepath}")

                            except Exception as e:
                                print(f"❌ Failed to download file {file_id}: {e}")

    return downloaded_files


def extract_file_ids(response) -> List[str]:
    """
    Extract all file IDs from an API response.

    Args:
        response: The Anthropic API response object

    Returns:
        List of file IDs found in the response
    """
    file_ids = []

    for block in response.content:
        # Check for bash_code_execution_tool_result blocks (Skills API format)
        if block.type == "bash_code_execution_tool_result":
            if hasattr(block, "content") and hasattr(block.content, "content"):
                if isinstance(block.content.content, list):
                    for output_block in block.content.content:
                        if hasattr(output_block, "file_id"):
                            file_ids.append(output_block.file_id)

    return file_ids


def download_single_file(
    client, file_id: str, output_path: str, betas: List[str] = None
) -> bool:
    """
    Download a single file by its file ID.

    Args:
        client: Anthropic client instance
        file_id: The file ID to download
        output_path: Where to save the file
        betas: Optional beta flags (default: ["files-api-2025-04-14"])

    Returns:
        True if successful, False otherwise
    """
    if betas is None:
        betas = ["files-api-2025-04-14"]

    try:
        # Download the file
        file_content = client.beta.files.download(file_id=file_id, betas=betas)

        # Save to disk
        with open(output_path, "wb") as f:
            file_content.write_to_file(f.name)

        print(f" Downloaded {file_id} to {output_path}")
        return True

    except Exception as e:
        print(f" Failed to download {file_id}: {e}")
        return False
