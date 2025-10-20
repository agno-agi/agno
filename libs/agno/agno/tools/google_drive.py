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
- GOOGLE_CLOUD_QUOTA_PROJECT_ID: Google Cloud quota project ID

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
   - Enable the OAuth Consent Screen if you haven't already
   - After enabling the Consent Screen, click on "Create Credentials" > "OAuth client ID"
   - You'll receive:
     * Client ID (GOOGLE_CLIENT_ID)
     * Client Secret (GOOGLE_CLIENT_SECRET)
   - The Project ID (GOOGLE_PROJECT_ID) is visible in the project dropdown at the top of the page

5. Add auth redirect URI:
   - Go to https://console.cloud.google.com/auth/clients
   - Add `http://localhost:5050` as a recognized redirect URI OR with http://localhost:{PORT_NUMBER}


6. Set up environment variables:
   Create a .envrc file in your project root with:
   ``
   export GOOGLE_CLIENT_ID=your_client_id_here
   export GOOGLE_CLIENT_SECRET=your_client_secret_here
   export GOOGLE_PROJECT_ID=your_project_id_here
   export GOOGLE_REDIRECT_URI=http://localhost/  # Default value
   export GOOGLE_AUTHENTICATION_PORT=5050  # Port for OAuth redirect
   export GOOGLE_CLOUD_QUOTA_PROJECT_ID=your_quota_project_id_here
   ``

---

Remember to install the dependencies using `pip install google google-auth-oauthlib`

Important Points to Note :
1. The first time you run the application, it will open a browser window for OAuth authentication.
2. A token.json file will be created to store the authentication credentials for future use.

You can customize the authentication port by setting the `GOOGLE_AUTHENTICATION_PORT` environment variable.
This will be used in the `run_local_server` method for OAuth authentication.

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
            # Set quota project on credentials if available
            creds_to_use = self.creds
            if hasattr(self, "quota_project_id") and self.quota_project_id:
                creds_to_use = self.creds.with_quota_project(self.quota_project_id)
            self.service = build("drive", "v3", credentials=creds_to_use)
        return func(self, *args, **kwargs)

    return wrapper


class GoogleDriveTools(Toolkit):
    # Default scopes for Google Drive API access
    DEFAULT_SCOPES = ["https://www.googleapis.com/auth/drive.file", "https://www.googleapis.com/auth/drive.readonly"]

    def __init__(
        self,
        auth_port: Optional[int] = 5050,
        creds: Optional[Credentials] = None,
        scopes: Optional[List[str]] = None,
        creds_path: Optional[str] = None,
        token_path: Optional[str] = None,
        quota_project_id: Optional[str] = None,
        **kwargs,
    ):
        self.creds: Optional[Credentials] = creds
        self.service: Optional[Resource] = None
        self.credentials_path = creds_path
        self.token_path = token_path
        self.scopes = scopes or []
        self.scopes.extend(self.DEFAULT_SCOPES)

        self.quota_project_id = quota_project_id or getenv("GOOGLE_CLOUD_QUOTA_PROJECT_ID")
        if not self.quota_project_id:
            raise ValueError("GOOGLE_CLOUD_QUOTA_PROJECT_ID is not set")

        self.auth_port: int = int(getenv("GOOGLE_AUTH_PORT", str(auth_port)))
        if not self.auth_port:
            raise ValueError("GOOGLE_AUTH_PORT is not set")

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

        token_file = Path(self.token_path or "token.json")
        creds_file = Path(self.credentials_path or "credentials.json")

        if token_file.exists():
            self.creds = Credentials.from_authorized_user_file(str(token_file), self.scopes)
        if not self.creds or not self.creds.valid:
            if self.creds and self.creds.expired and self.creds.refresh_token:
                self.creds.refresh(Request())
            else:
                client_config = {
                    "installed": {
                        "client_id": getenv("GOOGLE_CLIENT_ID"),
                        "client_secret": getenv("GOOGLE_CLIENT_SECRET"),
                        "project_id": getenv("GOOGLE_PROJECT_ID"),
                        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                        "token_uri": "https://oauth2.googleapis.com/token",
                        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                        "redirect_uris": [getenv("GOOGLE_REDIRECT_URI", "http://localhost")],
                    }
                }
                # File based authentication
                if creds_file.exists():
                    flow = InstalledAppFlow.from_client_secrets_file(str(creds_file), self.scopes)
                else:
                    flow = InstalledAppFlow.from_client_config(client_config, self.scopes)
                # Opens up a browser window for OAuth authentication
                self.creds = flow.run_local_server(port=self.auth_port)  # type: ignore

            token_file.write_text(self.creds.to_json()) if self.creds else None

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
                self.service.files()  # type: ignore
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
                self.service.files()  # type: ignore
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
            request = self.service.files().get_media(fileId=file_id)  # type: ignore
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
