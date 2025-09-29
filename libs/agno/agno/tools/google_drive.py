"""
Google Drive API integration for file management and sharing.


This module provides functions to interact with Google Drive, including listing,
uploading, and downloading files.
It uses the Google Drive API and handles authentication via OAuth2.

Required Environment Variables:
-----------------------------
- GOOGLE_CLIENT_ID: Google OAuth client ID
- GOOGLE_CLIENT_SECRET: Google OAuth client secret
- GOOGLE_PROJECT_ID: Google Cloud project ID
- GOOGLE_REDIRECT_URI: Google OAuth redirect URI (default: http://localhost)


How to Get These Credentials:
---------------------------
1. Go to Google Cloud Console (https://console.cloud.google.com)
2. Create a new project or select an existing one
3. Enable the Google Drive API:
   - Go to "APIs & Services" > "Enable APIs and Services"
   - Search for "Google Drive API"
   - Click "Enable"

4. Create OAuth 2.0 credentials:
   - Go to "APIs & Services" > "Credentials"
   - Click "Create Credentials" > "OAuth client ID"
   - Go through the OAuth consent screen setup
   - Give it a name and click "Create"
   - You'll receive:
     * Client ID (GOOGLE_CLIENT_ID)
     * Client Secret (GOOGLE_CLIENT_SECRET)
   - The Project ID (GOOGLE_PROJECT_ID) is visible in the project dropdown at the top of the page

5. Add auth redirect URI:
   - Go to https://console.cloud.google.com/auth/clients and add the redirect URI as http://127.0.0.1/


6. Set up environment variables:
   Create a .envrc file in your project root with:
   ```
   export GOOGLE_CLIENT_ID=your_client_id_here
   export GOOGLE_CLIENT_SECRET=your_client_secret_here
   export GOOGLE_PROJECT_ID=your_project_id_here
   export GOOGLE_REDIRECT_URI=http://127.0.0.1/  # Default value
   ```

"""

import mimetypes
from functools import wraps
from os import getenv
from pathlib import Path
from typing import Any, List, Optional, Union

from agno.tools import Toolkit

try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import Resource, build
    from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
except ImportError:
    raise ImportError(
        "Google client library for Python not found , install it using `pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib`"
    )


def authenticate(func):
    """Decorator to ensure authentication before executing a function."""

    @wraps(func)
    def wrapper(self, *args, **kwargs):
        if not self.creds or not self.creds.valid:
            self._auth()
        if not self.service:
            self.service = build("drive", "v3", credentials=self.creds)
        return func(self, *args, **kwargs)

    return wrapper


class GoogleDriveTools(Toolkit):
    # Default scopes for Google Drive API access
    DEFAULT_SCOPES = ["https://www.googleapis.com/auth/drive.file", "https://www.googleapis.com/auth/drive.readonly"]

    def __init__(self, creds: Optional[Credentials] = None, scopes: Optional[List[str]] = None, **kwargs):
        self.creds: Optional[Credentials] = creds
        self.service: Optional[Resource] = None
        self.scopes = scopes or []
        self.scopes.extend(self.DEFAULT_SCOPES)
        tools: List[Any] = [
            self.list_files,
        ]
        super().__init__(name="google_drive_tools", tools=tools, **kwargs)
        if not self.scopes:
            # Add read permission by default
            self.scopes.append(self.DEFAULT_SCOPES[1])  # 'drive.readonly'
            # Add write permission if allow_update is True
            if getattr(self, "allow_update", False):
                self.scopes.append(self.DEFAULT_SCOPES[0])  # 'drive.file'

    def _auth(self):
        """
        Authenticate and set up the Google Drive API client.
        This method checks if credentials are valid and refreshes or requests them if needed.
        """
        if self.creds and self.creds.valid:
            # Already authenticated
            return
        if self.creds and self.creds.expired and self.creds.refresh_token:
            self.creds.refresh(Request())
            return
        # Prompt for credentials if not available
        client_id = getenv("GOOGLE_CLIENT_ID")
        client_secret = getenv("GOOGLE_CLIENT_SECRET")
        redirect_uri = getenv("GOOGLE_REDIRECT_URI", "http://localhost")
        if not client_id or not client_secret:
            raise ValueError(
                "Google Drive authentication failed: Please set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in your environment variables."
            )
        flow = InstalledAppFlow.from_client_config(
            {
                "installed": {
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "redirect_uris": [redirect_uri],
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                }
            },
            self.scopes,
        )
        self.creds = flow.run_local_server(port=0)

    @authenticate
    def list_files(self, query: Optional[str] = None, page_size: int = 10) -> List[dict]:
        """
        List files in your Google Drive.

        Args:
            query (Optional[str]): Optional search query to filter files (see Google Drive API docs).
            page_size (int): Maximum number of files to return.

        Returns:
            List[dict]: List of file metadata dictionaries.
        """
        if not self.service:
            raise ValueError("Google Drive service is not initialized. Please authenticate first.")
        try:
            results = (
                self.service.files()
                .list(q=query, pageSize=page_size, fields="nextPageToken, files(id, name, mimeType, modifiedTime)")
                .execute()
            )
            items = results.get("files", [])
            return items
        except Exception as error:
            print(f"Could not list files: {error}")
            return []

    @authenticate
    def upload_file(self, file_path: Union[str, Path], mime_type: Optional[str] = None) -> Optional[dict]:
        """
        Upload a file to your Google Drive.

        Args:
            file_path (Union[str, Path]): Path to the file you want to upload.
            mime_type (Optional[str]): MIME type of the file. If not provided, it will be guessed.

        Returns:
            Optional[dict]: Metadata of the uploaded file, or None if upload failed.
        """
        if not self.service:
            raise ValueError("Google Drive service is not initialized. Please authenticate first.")
        file_path = Path(file_path)
        if not file_path.exists() or not file_path.is_file():
            raise ValueError(f"The file '{file_path}' does not exist or is not a file.")
        if mime_type is None:
            mime_type, _ = mimetypes.guess_type(file_path.as_posix())
            if mime_type is None:
                mime_type = "application/octet-stream"  # Default MIME type

        file_metadata = {"name": file_path.name}
        media = MediaFileUpload(file_path.as_posix(), mimetype=mime_type)

        try:
            uploaded_file = (
                self.service.files()
                .create(body=file_metadata, media_body=media, fields="id, name, mimeType, modifiedTime")
                .execute()
            )
            return uploaded_file
        except Exception as error:
            print(f"Could not upload file '{file_path}': {error}")
            return None

    @authenticate
    def download_file(self, file_id: str, dest_path: Union[str, Path]) -> Optional[Path]:
        """
        Download a file from your Google Drive.

        Args:
            file_id (str): The ID of the file you want to download.
            dest_path (Union[str, Path]): Where to save the downloaded file.

        Returns:
            Optional[Path]: The path to the downloaded file, or None if download failed.
        """
        if not self.service:
            raise ValueError("Google Drive service is not initialized. Please authenticate first.")
        dest_path = Path(dest_path)
        try:
            request = self.service.files().get_media(fileId=file_id)
            with open(dest_path, "wb") as fh:
                downloader = MediaIoBaseDownload(fh, request)
                done = False
                while not done:
                    status, done = downloader.next_chunk()
                    print(f"Download progress: {int(status.progress() * 100)}%.")
            return dest_path
        except Exception as error:
            print(f"Could not download file '{file_id}': {error}")
            return None
