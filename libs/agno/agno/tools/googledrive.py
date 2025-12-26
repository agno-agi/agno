"""
Google Drive Toolkit for Agno

Provides tools to interact with Google Drive:
- List files with pagination
- Search files
- Get file info
- Upload files
- Download files
- Create folders
- Delete files

Authentication:
---------------
Requires either a `credentials.json` file or environment variables:
- GOOGLE_CLIENT_ID
- GOOGLE_CLIENT_SECRET
- GOOGLE_PROJECT_ID
- GOOGLE_REDIRECT_URI (default: http://localhost)

Google API References:
- https://developers.google.com/drive/api/v3/about-sdk
"""

import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from agno.tools import Toolkit
from agno.utils.log import logger

try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import Resource, build
    from googleapiclient.errors import HttpError
except ImportError:
    raise ImportError(
        "`google-api-python-client` `google-auth-httplib2` `google-auth-oauthlib` not installed.\n"
        "Install with: pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib"
    )


class GoogleDriveTools(Toolkit):
    """A toolkit for interacting with Google Drive files and folders."""

    DEFAULT_SCOPES = {
        "read": "https://www.googleapis.com/auth/drive.readonly",
        "write": "https://www.googleapis.com/auth/drive.file",
        "full": "https://www.googleapis.com/auth/drive",
        "metadata": "https://www.googleapis.com/auth/drive.metadata.readonly",
    }

    service: Optional[Resource]

    def __init__(
        self,
        creds_path: Optional[str] = None,
        token_path: Optional[str] = None,
        scopes: Optional[List[str]] = None,
        oauth_port: int = 0,
        **kwargs,
    ):
        """Initialize GoogleDriveTools."""
        self.creds = None
        self.credentials_path = creds_path
        self.token_path = token_path
        self.oauth_port = oauth_port
        self.scopes = scopes or [
            self.DEFAULT_SCOPES["metadata"],
            self.DEFAULT_SCOPES["read"],
            self.DEFAULT_SCOPES["write"],
        ]
        self.service: Optional[Resource] = None

        tools: List[Callable[..., Any]] = [
            self.list_files,
            self.get_file_info,
            self.search_files,
            self.upload_file,
            self.download_file,
            self.create_folder,
            self.delete_file,
        ]
        super().__init__(name="google_drive_tools", tools=tools, **kwargs)

    def _auth(self):
        """Authenticate with Google Drive API."""
        token_file = Path(self.token_path or "token.json")
        creds_file = Path(self.credentials_path or "credentials.json")

        if token_file.exists():
            self.creds = Credentials.from_authorized_user_file(str(token_file), self.scopes)

        if not self.creds or not self.creds.valid:
            if self.creds and self.creds.expired and self.creds.refresh_token:
                logger.info("Refreshing Google Drive credentials...")
                self.creds.refresh(Request())
            else:
                client_config = {
                    "installed": {
                        "client_id": os.getenv("GOOGLE_CLIENT_ID"),
                        "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
                        "project_id": os.getenv("GOOGLE_PROJECT_ID"),
                        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                        "token_uri": "https://oauth2.googleapis.com/token",
                        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                        "redirect_uris": [os.getenv("GOOGLE_REDIRECT_URI", "http://localhost")],
                    }
                }
                if creds_file.exists():
                    flow = InstalledAppFlow.from_client_secrets_file(str(creds_file), self.scopes)
                else:
                    flow = InstalledAppFlow.from_client_config(client_config, self.scopes)
                self.creds = flow.run_local_server(port=self.oauth_port)

            if self.creds:
                token_file.write_text(self.creds.to_json())

        self.service = build("drive", "v3", credentials=self.creds)

    def _ensure_service(self):
        if not self.service:
            self._auth()

    # ---------------------------
    # Core Operations
    # ---------------------------

    def list_files(
        self, folder_id: Optional[str] = None, page_size: int = 10, page_token: Optional[str] = None
    ) -> Dict[str, Any]:
        """List files/folders with optional pagination."""
        self._ensure_service()

        assert self.service is not None

        try:
            query = None
            if folder_id is None:
                query = "'root' in parents and trashed=false"
            else:
                query = f"'{folder_id}' in parents and trashed=false"

            results = (
                self.service.files()
                .list(
                    q=query,
                    pageSize=page_size,
                    pageToken=page_token,
                    fields="nextPageToken, files(id,name,mimeType,size,createdTime,modifiedTime,parents,webViewLink)",
                    orderBy="name",
                )
                .execute()
            )

            return {
                "files": results.get("files", []),
                "nextPageToken": results.get("nextPageToken"),
            }
        except HttpError as e:
            logger.error(f"Drive API error: {e}")
            return {"error": str(e)}

    def search_files(self, query: str, page_size: int = 10, page_token: Optional[str] = None) -> Dict[str, Any]:
        """Search for files by query string."""
        self._ensure_service()

        assert self.service is not None

        try:
            results = (
                self.service.files()
                .list(
                    q=f"{query} and trashed=false",
                    pageSize=page_size,
                    pageToken=page_token,
                    fields="nextPageToken, files(id,name,mimeType,size,createdTime,modifiedTime,parents,webViewLink)",
                    orderBy="modifiedTime desc",
                )
                .execute()
            )

            return {
                "files": results.get("files", []),
                "nextPageToken": results.get("nextPageToken"),
            }
        except HttpError as e:
            logger.error(f"Drive API error: {e}")
            return {"error": str(e)}

    def get_file_info(self, file_id: str) -> Dict[str, Any]:
        """Get detailed information for a file."""
        self._ensure_service()

        assert self.service is not None

        try:
            return (
                self.service.files()
                .get(
                    fileId=file_id,
                    fields="id,name,mimeType,size,createdTime,modifiedTime,parents,webViewLink,description,owners,permissions,capabilities",
                )
                .execute()
            )
        except HttpError as e:
            logger.error(f"Drive API error: {e}")
            return {"error": str(e)}

    def upload_file(self, local_path: str, folder_id: Optional[str] = None) -> Dict[str, Any]:
        """Upload a local file to Google Drive."""
        from googleapiclient.http import MediaFileUpload

        self._ensure_service()

        assert self.service is not None

        try:
            file_metadata: Dict[str, Any] = {"name": Path(local_path).name}
            if folder_id:
                file_metadata["parents"] = [folder_id]

            media = MediaFileUpload(local_path, resumable=True)
            return (
                self.service.files()
                .create(body=file_metadata, media_body=media, fields="id, name, webViewLink")
                .execute()
            )
        except HttpError as e:
            logger.error(f"Drive API error: {e}")
            return {"error": str(e)}

    def download_file(self, file_id: str, destination_path: str) -> Dict[str, Any]:
        """Download a file from Google Drive to local path."""
        import io

        from googleapiclient.http import MediaIoBaseDownload

        self._ensure_service()

        assert self.service is not None

        try:
            request = self.service.files().get_media(fileId=file_id)
            fh = io.FileIO(destination_path, "wb")
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                status, done = downloader.next_chunk()
                logger.info(f"Download progress: {int(status.progress() * 100)}%")
            return {"message": f"File downloaded to {destination_path}"}
        except HttpError as e:
            logger.error(f"Drive API error: {e}")
            return {"error": str(e)}

    def create_folder(self, name: str, parent_id: Optional[str] = None) -> Dict[str, Any]:
        """Create a folder in Google Drive."""
        self._ensure_service()

        assert self.service is not None

        try:
            file_metadata: Dict[str, Any] = {"name": name, "mimeType": "application/vnd.google-apps.folder"}
            if parent_id:
                file_metadata["parents"] = [parent_id]

            return self.service.files().create(body=file_metadata, fields="id, name, webViewLink").execute()
        except HttpError as e:
            logger.error(f"Drive API error: {e}")
            return {"error": str(e)}

    def delete_file(self, file_id: str, permanent: bool = False) -> Dict[str, Any]:
        """
        Delete a file from Google Drive.

        Args:
            file_id (str): The ID of the file to delete.
            permanent (bool): If True, permanently deletes the file (bypasses trash).
                            If False (default), moves the file to Trash (soft delete).

        Returns:
            dict: Message or error.
        """
        self._ensure_service()

        assert self.service is not None

        try:
            if permanent:
                # Hard delete – file is gone forever
                self.service.files().delete(fileId=file_id).execute()
                return {"message": f"File {file_id} permanently deleted"}
            else:
                # Soft delete – move to trash
                self.service.files().update(fileId=file_id, body={"trashed": True}).execute()
                return {"message": f"File {file_id} moved to Trash"}
        except HttpError as e:
            logger.error(f"Drive API error: {e}")
            return {"error": str(e)}
