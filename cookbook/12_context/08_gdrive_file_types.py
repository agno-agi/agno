"""
Google Drive File Type Handling
===============================

Demonstrates how read_file handles different file types in Google Drive:

1. Google Workspace files (Docs, Sheets, Slides) → exported to text
2. Text files (.txt, .json, .csv, .md) → decoded as UTF-8
3. Binary files (.docx, .pdf, images) → clear error with guidance

Setup:
    1. Create a service account in Google Cloud Console
    2. Download the JSON key file
    3. Share test files/folders with the service account email
    4. Set GOOGLE_SERVICE_ACCOUNT_FILE=/path/to/key.json

Requires:
    OPENAI_API_KEY
    GOOGLE_SERVICE_ACCOUNT_FILE
"""

from __future__ import annotations

import json
from os import getenv

from agno.context.gdrive.tools import AllDrivesGoogleDriveTools

DIVIDER = "=" * 60


def test_file_type_handling():
    """Test read_file behavior across different MIME types."""
    service_account = getenv("GOOGLE_SERVICE_ACCOUNT_FILE")
    if not service_account:
        print("GOOGLE_SERVICE_ACCOUNT_FILE not set - skipping live test")
        print("\nRunning MIME type detection demo instead...\n")
        demo_mime_detection()
        return

    print(f"Service account: {service_account}\n")

    tools = AllDrivesGoogleDriveTools(
        service_account_path=service_account,
        list_files=True,
        search_files=True,
        read_file=True,
    )

    # Search for files to test
    print(DIVIDER)
    print("Searching for test files...")
    print(DIVIDER)

    result = tools.search_files(max_results=20)
    data = json.loads(result)

    if "error" in data:
        print(f"Search error: {data['error']}")
        return

    files = data.get("files", [])
    print(f"Found {len(files)} files\n")

    if not files:
        print("No files found. Share some files with the service account.")
        return

    # Group files by type
    workspace_files = []
    text_files = []
    binary_files = []

    for f in files:
        mime = f.get("mimeType", "")

        if mime.startswith("application/vnd.google-apps."):
            if mime in (
                "application/vnd.google-apps.document",
                "application/vnd.google-apps.spreadsheet",
                "application/vnd.google-apps.presentation",
            ):
                workspace_files.append(f)
            # Skip folders, forms, etc.
        elif mime.startswith(("text/", "application/json", "application/xml")):
            text_files.append(f)
        elif mime.startswith(
            (
                "application/vnd.openxmlformats",
                "application/vnd.ms-",
                "application/pdf",
                "application/zip",
                "image/",
                "video/",
                "audio/",
            )
        ):
            binary_files.append(f)

    # Test one file from each category
    print(DIVIDER)
    print("Testing file type handling")
    print(DIVIDER)

    if workspace_files:
        f = workspace_files[0]
        print(f"\n1. GOOGLE WORKSPACE: {f['name']}")
        print(f"   MIME: {f['mimeType']}")
        result = tools.read_file(f["id"])
        data = json.loads(result)
        if "error" in data:
            print(f"   ERROR: {data['error']}")
        else:
            content = data.get("content", "")
            print(f"   RESULT: {len(content)} chars of text extracted")
            print(
                f"   PREVIEW: {content[:100]}..."
                if len(content) > 100
                else f"   PREVIEW: {content}"
            )
    else:
        print("\n1. GOOGLE WORKSPACE: (no files found)")

    if text_files:
        f = text_files[0]
        print(f"\n2. TEXT FILE: {f['name']}")
        print(f"   MIME: {f['mimeType']}")
        result = tools.read_file(f["id"])
        data = json.loads(result)
        if "error" in data:
            print(f"   ERROR: {data['error']}")
        else:
            content = data.get("content", "")
            print(f"   RESULT: {len(content)} chars decoded as UTF-8")
            print(
                f"   PREVIEW: {content[:100]}..."
                if len(content) > 100
                else f"   PREVIEW: {content}"
            )
    else:
        print("\n2. TEXT FILE: (no files found)")

    if binary_files:
        f = binary_files[0]
        print(f"\n3. BINARY FILE: {f['name']}")
        print(f"   MIME: {f['mimeType']}")
        result = tools.read_file(f["id"])
        data = json.loads(result)
        if "error" in data:
            print("   RESULT: Clear error returned (expected)")
            print(f"   ERROR: {data['error']}")
        else:
            content = data.get("content", "")
            print(f"   BUG: Got {len(content)} chars - should have returned error!")
            print(f"   PREVIEW: {repr(content[:50])}")
    else:
        print("\n3. BINARY FILE: (no files found)")

    print(f"\n{DIVIDER}")
    print("Summary")
    print(DIVIDER)
    print(f"Workspace files found: {len(workspace_files)}")
    print(f"Text files found: {len(text_files)}")
    print(f"Binary files found: {len(binary_files)}")


def demo_mime_detection():
    """Demo MIME type detection without live Drive access."""
    from agno.context.gdrive.tools import _is_binary_mime
    from agno.tools.google.drive import GoogleDriveTools, WorkspaceType

    print(DIVIDER)
    print("MIME Type Detection Demo")
    print(DIVIDER)

    test_cases = [
        # Google Workspace - exportable
        ("application/vnd.google-apps.document", "Google Doc"),
        ("application/vnd.google-apps.spreadsheet", "Google Sheet"),
        ("application/vnd.google-apps.presentation", "Google Slides"),
        # Google Workspace - non-exportable
        ("application/vnd.google-apps.drawing", "Google Drawing"),
        ("application/vnd.google-apps.form", "Google Form"),
        # Binary files
        (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".docx",
        ),
        ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".xlsx"),
        ("application/pdf", ".pdf"),
        ("image/png", ".png"),
        ("video/mp4", ".mp4"),
        ("application/zip", ".zip"),
        # Text files
        ("text/plain", ".txt"),
        ("application/json", ".json"),
        ("text/csv", ".csv"),
        ("text/markdown", ".md"),
        ("text/x-python", ".py"),
    ]

    print(f"\n{'MIME Type':<65} {'Name':<12} {'Handling':<20}")
    print("-" * 100)

    for mime, name in test_cases:
        if mime in GoogleDriveTools.TEXT_EXPORT_TYPES:
            handling = "Export to text"
        elif mime.startswith(WorkspaceType.WORKSPACE_PREFIX):
            handling = "Error (non-exportable)"
        elif _is_binary_mime(mime):
            handling = "Error (binary)"
        else:
            handling = "UTF-8 decode"

        print(f"{mime:<65} {name:<12} {handling:<20}")

    print(f"\n{DIVIDER}")
    print("Legend:")
    print("  Export to text      - Google API converts to text/plain or text/csv")
    print(
        "  Error (non-exportable) - Workspace type without text export (Drawings, Forms)"
    )
    print("  Error (binary)      - Binary file, cannot decode as text")
    print("  UTF-8 decode        - Download and decode as UTF-8 text")


if __name__ == "__main__":
    test_file_type_handling()
