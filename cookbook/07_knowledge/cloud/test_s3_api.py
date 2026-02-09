#!/usr/bin/env python3
"""
Test S3 Sources API
============================================================

This script tests the S3 file browsing API endpoints directly.
Run this after starting the s3_sources.py server.

Usage:
    # Terminal 1: Start the server
    .venvs/demo/bin/python cookbook/07_knowledge/cloud/s3_sources.py

    # Terminal 2: Run this test
    .venvs/demo/bin/python cookbook/07_knowledge/cloud/test_s3_api.py
"""

import json
import sys

import httpx

BASE_URL = "http://localhost:7777/v1"
KNOWLEDGE_ID = "s3-sources-demo"  # Must match the knowledge name in s3_sources.py


def print_json(data):
    """Pretty print JSON data."""
    print(json.dumps(data, indent=2, default=str))


def test_list_sources():
    """Test listing all configured content sources."""
    print("\n" + "=" * 60)
    print("TEST: List Content Sources")
    print("=" * 60)

    response = httpx.get(f"{BASE_URL}/knowledge/{KNOWLEDGE_ID}/sources")

    print(f"Status: {response.status_code}")
    if response.status_code == 200:
        sources = response.json()
        print(f"Found {len(sources)} source(s):")
        print_json(sources)
        return sources
    else:
        print(f"Error: {response.text}")
        return []


def test_list_files(source_id: str, prefix: str = "", limit: int = 10):
    """Test listing files in a specific source."""
    print("\n" + "=" * 60)
    print(f"TEST: List Files in '{source_id}' (prefix='{prefix}')")
    print("=" * 60)

    params = {"limit": limit}
    if prefix:
        params["prefix"] = prefix

    response = httpx.get(
        f"{BASE_URL}/knowledge/{KNOWLEDGE_ID}/sources/{source_id}/files",
        params=params,
    )

    print(f"Status: {response.status_code}")
    if response.status_code == 200:
        result = response.json()
        meta = result.get("meta", {})
        print(f"Folders: {len(result.get('folders', []))}")
        print(f"Files: {len(result.get('files', []))}")
        print(f"Page: {meta.get('page', 1)} of {meta.get('total_pages', 1)}")
        print(f"Total count: {meta.get('total_count', 0)}")
        print_json(result)
        return result
    else:
        print(f"Error: {response.text}")
        return None


def test_pagination(source_id: str, limit: int = 2):
    """Test pagination through files."""
    print("\n" + "=" * 60)
    print(f"TEST: Pagination (limit={limit})")
    print("=" * 60)

    # Get first page to find total pages
    response = httpx.get(
        f"{BASE_URL}/knowledge/{KNOWLEDGE_ID}/sources/{source_id}/files",
        params={"limit": limit, "page": 1},
    )

    if response.status_code != 200:
        print(f"Error: {response.text}")
        return

    result = response.json()
    meta = result.get("meta", {})
    total_pages = meta.get("total_pages", 1)
    total_count = meta.get("total_count", 0)

    print(f"Total pages: {total_pages}")
    print(f"Total files: {total_count}")

    # Iterate through pages
    for page in range(1, min(total_pages + 1, 5)):  # Max 5 pages for demo
        response = httpx.get(
            f"{BASE_URL}/knowledge/{KNOWLEDGE_ID}/sources/{source_id}/files",
            params={"limit": limit, "page": page},
        )

        if response.status_code != 200:
            print(f"Error on page {page}: {response.text}")
            break

        result = response.json()
        file_count = len(result.get("files", []))
        print(f"Page {page}: {file_count} files")


def test_folder_navigation(source_id: str):
    """Test navigating into folders."""
    print("\n" + "=" * 60)
    print("TEST: Folder Navigation")
    print("=" * 60)

    # Get root level
    result = test_list_files(source_id)
    if not result:
        return

    folders = result.get("folders", [])
    if folders:
        # Navigate into first folder
        first_folder = folders[0]
        print(f"\nNavigating into folder: {first_folder['name']}")
        test_list_files(source_id, prefix=first_folder["prefix"])


def test_invalid_source():
    """Test error handling for invalid source."""
    print("\n" + "=" * 60)
    print("TEST: Invalid Source ID")
    print("=" * 60)

    response = httpx.get(
        f"{BASE_URL}/knowledge/{KNOWLEDGE_ID}/sources/nonexistent/files"
    )
    print(f"Status: {response.status_code}")
    print(f"Response: {response.text}")


def main():
    print("S3 Sources API Test Suite")
    print("=" * 60)

    # Check server is running
    try:
        httpx.get(f"{BASE_URL}/health", timeout=2)
    except httpx.ConnectError:
        print("Error: Server not running. Start it first:")
        print("  .venvs/demo/bin/python cookbook/07_knowledge/cloud/s3_sources.py")
        sys.exit(1)

    # Run tests
    sources = test_list_sources()

    if sources:
        source_id = sources[0]["id"]
        test_list_files(source_id)
        test_folder_navigation(source_id)
        test_pagination(source_id, limit=2)
    else:
        print("\nNo sources configured. Add an S3Config to test file listing.")

    test_invalid_source()

    print("\n" + "=" * 60)
    print("Tests complete")
    print("=" * 60)


if __name__ == "__main__":
    main()
