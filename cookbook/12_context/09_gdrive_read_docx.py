"""
Google Drive .docx Text Extraction Demo

Demonstrates reading .docx files from Google Drive with automatic text extraction.
Requires: pip install python-docx

Setup:
1. Create a Google Cloud project
2. Enable the Google Drive API
3. Create a service account and download the JSON key
4. Share your Google Drive folder with the service account email
5. Set GOOGLE_SERVICE_ACCOUNT_FILE to the path of the JSON key
"""

import json

from agno.context.gdrive.tools import AllDrivesGoogleDriveTools

print("=" * 60)
print("Google Drive .docx Text Extraction Demo")
print("=" * 60)

try:
    import docx  # noqa: F401

    print("python-docx is installed - .docx text extraction enabled")
except ImportError:
    print("WARNING: python-docx not installed")
    print("Install with: pip install python-docx")
    print("Without it, .docx files will show an error.\n")

tools = AllDrivesGoogleDriveTools()

# Search for .docx files
print("\n--- Step 1: Search for .docx files ---")
docx_mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
result = tools.search_files(f"mimeType='{docx_mime}'", max_results=5)
data = json.loads(result)

if "error" in data:
    print(f"Error: {data['error']}")
elif data.get("files"):
    print(f"Found {len(data['files'])} .docx files:")
    for f in data["files"]:
        print(f"  - {f['name']} (id: {f['id'][:20]}...)")

    # Try to read the first one
    first_file = data["files"][0]
    print(f"\n--- Step 2: Read '{first_file['name']}' ---")
    content_result = tools.read_file(first_file["id"])
    content_data = json.loads(content_result)

    if "error" in content_data:
        print(f"Error: {content_data['error']}")
    else:
        text = content_data.get("content", "")
        print(f"Extraction method: {content_data.get('extractedFrom', 'utf-8 decode')}")
        print(f"Content length: {content_data.get('contentLength', 0)} characters")
        print(f"\nExtracted text (first 1000 chars):")
        print("-" * 40)
        print(text[:1000])
        if len(text) > 1000:
            print(f"... ({len(text) - 1000} more characters)")
        print("-" * 40)
else:
    print("No .docx files found.")
    print("\nTo test, upload a .docx file to a Google Drive folder")
    print("that's shared with your service account.")

# Also test other file types
print("\n--- Step 3: Test other file types ---")

# Search for Google Docs (should export to text)
print("\nGoogle Docs (exportable):")
result = tools.search_files(
    "mimeType='application/vnd.google-apps.document'", max_results=2
)
data = json.loads(result)
if data.get("files"):
    for f in data["files"][:2]:
        print(f"  - {f['name']}")
else:
    print("  (none found)")

# Search for PDFs (binary, should error)
print("\nPDFs (binary - will show error):")
result = tools.search_files("mimeType='application/pdf'", max_results=1)
data = json.loads(result)
if data.get("files"):
    f = data["files"][0]
    print(f"  - {f['name']}")
    content_result = tools.read_file(f["id"])
    content_data = json.loads(content_result)
    if "error" in content_data:
        print(f"    -> {content_data['error'][:80]}...")
else:
    print("  (none found)")

# Search for text files (should decode directly)
print("\nText files (direct decode):")
result = tools.search_files("mimeType='text/plain'", max_results=1)
data = json.loads(result)
if data.get("files"):
    f = data["files"][0]
    print(f"  - {f['name']}")
    content_result = tools.read_file(f["id"])
    content_data = json.loads(content_result)
    if "error" in content_data:
        print(f"    -> Error: {content_data['error'][:60]}...")
    else:
        print(f"    -> Read {content_data.get('contentLength', 0)} chars successfully")
else:
    print("  (none found)")

print("\n" + "=" * 60)
print("Test complete!")
print("=" * 60)
