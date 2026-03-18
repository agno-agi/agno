"""
Google Drive tools for listing, searching, reading, uploading, and downloading files.

Required Setup:
--------------
**Option A — OAuth (interactive, for local development):**
1. Go to Google Cloud Console -> APIs & Services -> Enable Google Drive API
2. Create OAuth 2.0 credentials (Desktop app)
3. Set environment variables:
   - GOOGLE_CLIENT_ID
   - GOOGLE_CLIENT_SECRET
   - GOOGLE_PROJECT_ID
4. First run opens a browser for consent; token is cached in token.json

**Option B — Service Account (headless, for servers):**
1. Create a service account in Google Cloud Console
2. Download the JSON key file
3. Set GOOGLE_SERVICE_ACCOUNT_FILE to the path of the key file
4. Optionally set GOOGLE_DELEGATED_USER to impersonate a user via domain-wide delegation

Install dependencies: `pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib`
"""

import asyncio
import io
import json
import mimetypes
import textwrap
from functools import wraps
from os import getenv
from pathlib import Path
from typing import Any, List, Optional, Tuple, Union, cast

from agno.tools import Toolkit
from agno.utils.log import log_error

try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google.oauth2.service_account import Credentials as ServiceAccountCredentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import Resource, build
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
except ImportError:
    raise ImportError(
        "Google client library for Python not found, install it using "
        "`pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib`"
    )


class WorkspaceType:
    """Google Workspace MIME type constants."""

    DOCUMENT = "application/vnd.google-apps.document"
    SPREADSHEET = "application/vnd.google-apps.spreadsheet"
    PRESENTATION = "application/vnd.google-apps.presentation"
    DRAWING = "application/vnd.google-apps.drawing"
    SCRIPT = "application/vnd.google-apps.script"
    VID = "application/vnd.google-apps.vid"
    FOLDER = "application/vnd.google-apps.folder"

    @classmethod
    def is_workspace(cls, mime_type: str) -> bool:
        return mime_type.startswith("application/vnd.google-apps.")


DRIVE_QUERY_INSTRUCTIONS = textwrap.dedent(f"""\
    You have access to Google Drive tools for searching, reading, uploading, and downloading files.

    ## Drive Query Syntax
    Use these operators in search and list query parameters:
    - `name contains 'report'` — files with "report" in the name
    - `name = 'Budget 2025.xlsx'` — exact name match
    - `mimeType = '{WorkspaceType.DOCUMENT}'` — Google Docs only
    - `mimeType = '{WorkspaceType.SPREADSHEET}'` — Google Sheets only
    - `mimeType = 'application/pdf'` — PDF files only
    - `mimeType = '{WorkspaceType.FOLDER}'` — folders only
    - `modifiedTime > '2025-01-01T00:00:00'` — modified after date
    - `'<folder_id>' in parents` — files inside a specific folder
    - `sharedWithMe` — files shared with the user
    - `starred` — starred files
    - Combine with `and` / `or`: `name contains 'report' and mimeType = 'application/pdf'`
    - `trashed=false` is added automatically unless you include a trashed clause.""")


def authenticate(func):
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        try:
            if not self.creds or not self.creds.valid:
                self._auth()
            if not self.service:
                creds_to_use = self.creds
                # Set quota project on credentials if available
                if self.quota_project_id and hasattr(creds_to_use, "with_quota_project"):
                    creds_to_use = cast(Any, creds_to_use).with_quota_project(self.quota_project_id)
                self.service = build("drive", "v3", credentials=creds_to_use)
        except Exception as e:
            log_error(f"Google Drive authentication failed: {e}")
            return json.dumps({"error": f"Google Drive authentication failed: {e}"})
        return func(self, *args, **kwargs)

    return wrapper


class GoogleDriveTools(Toolkit):
    DEFAULT_SCOPES = {
        "read": "https://www.googleapis.com/auth/drive.readonly",
        "write": "https://www.googleapis.com/auth/drive.file",
        "full": "https://www.googleapis.com/auth/drive",
    }

    # Used by read_file — export Workspace files to text formats the LLM can consume
    TEXT_EXPORT_TYPES = {
        WorkspaceType.DOCUMENT: "text/plain",
        WorkspaceType.SPREADSHEET: "text/csv",
        WorkspaceType.PRESENTATION: "text/plain",
        WorkspaceType.SCRIPT: "application/json",
    }

    # Used by download_file — export Workspace files to best native format + extension
    DOWNLOAD_EXPORT_TYPES = {
        WorkspaceType.DOCUMENT: (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".docx",
        ),
        WorkspaceType.SPREADSHEET: (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ".xlsx",
        ),
        WorkspaceType.PRESENTATION: (
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            ".pptx",
        ),
        WorkspaceType.DRAWING: ("image/png", ".png"),
        WorkspaceType.SCRIPT: ("application/vnd.google-apps.script+json", ".json"),
        WorkspaceType.VID: ("video/mp4", ".mp4"),
    }

    # Partial response fields — only fetch what each tool needs
    METADATA_FIELDS = "id,name,mimeType,modifiedTime,size,owners,shared,webViewLink"
    SEARCH_FIELDS = "nextPageToken, files(id, name, mimeType, modifiedTime, size, owners(displayName, emailAddress))"
    READ_METADATA_FIELDS = "id,name,mimeType,modifiedTime,size,webViewLink"

    service: Optional[Resource]

    def __init__(
        self,
        # Authentication
        auth_port: Optional[int] = 5050,
        login_hint: Optional[str] = None,
        creds: Optional[Union[Credentials, ServiceAccountCredentials]] = None,
        scopes: Optional[List[str]] = None,
        creds_path: Optional[str] = None,  # OAuth client credentials JSON file path
        token_path: Optional[str] = None,  # OAuth token file path
        # Service account auth — alternative to OAuth for server/bot deployments
        service_account_path: Optional[str] = None,
        service_account_file: Optional[str] = None,
        delegated_user: Optional[str] = None,
        # Bills API usage to a different GCP project than the credential owner
        quota_project_id: Optional[str] = None,
        # Reading tools — enabled by default
        list_files: bool = True,
        search_files: bool = True,
        get_file_metadata: bool = True,
        read_file: bool = True,
        # Writing tools — disabled by default for safety
        upload_file: bool = False,
        download_file: bool = False,
        # Injected into agent system prompt with Drive query syntax
        instructions: Optional[str] = None,
        add_instructions: bool = True,
        **kwargs,
    ):
        if instructions is None:
            self.instructions = DRIVE_QUERY_INSTRUCTIONS
        else:
            self.instructions = instructions

        # Pre-built credentials skip the OAuth/service account flow entirely
        self.creds = creds
        self.service = None
        self.credentials_path = creds_path
        self.token_path = token_path
        self.service_account_path = service_account_path or service_account_file
        self.delegated_user = delegated_user
        # Pre-selects this email in the OAuth consent screen
        self.login_hint = login_hint
        self.quota_project_id = quota_project_id or getenv("GOOGLE_CLOUD_QUOTA_PROJECT_ID")

        self.auth_port = auth_port

        read_tools_enabled = any([list_files, search_files, get_file_metadata, read_file, download_file])

        # Auto-infer minimal scopes from enabled tools
        if scopes is None:
            resolved_scopes: List[str] = []
            if read_tools_enabled:
                resolved_scopes.append(self.DEFAULT_SCOPES["read"])
            if upload_file:
                resolved_scopes.append(self.DEFAULT_SCOPES["write"])
            if not resolved_scopes:
                resolved_scopes.append(self.DEFAULT_SCOPES["read"])
            self.scopes = list(dict.fromkeys(resolved_scopes))
        else:
            self.scopes = scopes

        # drive.file only covers app-created files — not sufficient for browsing all files
        read_scopes = {self.DEFAULT_SCOPES["read"], self.DEFAULT_SCOPES["full"]}
        write_scopes = {self.DEFAULT_SCOPES["write"], self.DEFAULT_SCOPES["full"]}

        if read_tools_enabled and not any(s in self.scopes for s in read_scopes):
            raise ValueError("A Google Drive read scope is required for enabled tools")
        if upload_file and not any(s in self.scopes for s in write_scopes):
            raise ValueError("A Google Drive write scope is required for enabled tools")

        tools: List[Any] = []
        async_tools: List[Tuple[Any, str]] = []

        # Reading
        if list_files:
            tools.append(self.list_files)
            async_tools.append((self.alist_files, "list_files"))
        if search_files:
            tools.append(self.search_files)
            async_tools.append((self.asearch_files, "search_files"))
        if get_file_metadata:
            tools.append(self.get_file_metadata)
            async_tools.append((self.aget_file_metadata, "get_file_metadata"))
        if read_file:
            tools.append(self.read_file)
            async_tools.append((self.aread_file, "read_file"))
        # Writing
        if upload_file:
            tools.append(self.upload_file)
            async_tools.append((self.aupload_file, "upload_file"))
        if download_file:
            tools.append(self.download_file)
            async_tools.append((self.adownload_file, "download_file"))

        super().__init__(
            name="google_drive_tools",
            tools=tools,
            async_tools=async_tools,
            instructions=self.instructions,
            add_instructions=add_instructions,
            **kwargs,
        )

    def _auth(self) -> None:
        """Authenticate with Google Drive API using service account or OAuth."""
        if self.creds and self.creds.valid:
            return

        # Service account takes priority
        service_account_path = self.service_account_path or getenv("GOOGLE_SERVICE_ACCOUNT_FILE")
        if service_account_path:
            service_account_creds = ServiceAccountCredentials.from_service_account_file(
                service_account_path,
                scopes=self.scopes,
            )
            delegated_user = self.delegated_user or getenv("GOOGLE_DELEGATED_USER")
            if delegated_user:
                service_account_creds = service_account_creds.with_subject(delegated_user)
            self.creds = service_account_creds
            self.creds.refresh(Request())
            return

        # OAuth flow
        token_file = Path(self.token_path or "token.json")
        creds_file = Path(self.credentials_path or "credentials.json")

        if token_file.exists():
            try:
                self.creds = Credentials.from_authorized_user_file(str(token_file), self.scopes)
            except ValueError:
                self.creds = None

        if self.creds and self.creds.expired and getattr(self.creds, "refresh_token", None):
            try:
                self.creds.refresh(Request())
            except Exception:
                self.creds = None

        if not self.creds or not self.creds.valid:
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
            if creds_file.exists():
                flow = InstalledAppFlow.from_client_secrets_file(str(creds_file), self.scopes)
            else:
                flow = InstalledAppFlow.from_client_config(client_config, self.scopes)
            run_kwargs: dict = {"port": self.auth_port, "prompt": "consent"}
            if self.login_hint:
                run_kwargs["login_hint"] = self.login_hint
            self.creds = flow.run_local_server(**run_kwargs)

        if self.creds and self.creds.valid:
            token_file.write_text(self.creds.to_json())

    def _get_file_metadata(self, file_id: str, fields: str) -> dict:
        service = cast(Resource, self.service)
        return service.files().get(fileId=file_id, fields=fields).execute()

    def _download_bytes(self, request: Any) -> bytes:
        """Download a Drive API media request into memory via MediaIoBaseDownload."""
        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(buffer, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return buffer.getvalue()

    def list_files(self, query: Optional[str] = None, page_size: int = 10) -> str:
        """
        Browse Google Drive files and folders. Returns metadata only, not file contents.
        Use for broad listing, recent files, or folder contents.

        Args:
            query (str): Optional Drive query string to filter results
            page_size (int): Maximum number of files to return

        Returns:
            str: JSON string with file metadata (name, type, modified date)
        """
        return self.search_files(query=query, max_results=page_size)

    async def alist_files(self, query: Optional[str] = None, page_size: int = 10) -> str:
        """
        Browse Google Drive files and folders (async). Returns metadata only, not file contents.

        Args:
            query (str): Optional Drive query string to filter results
            page_size (int): Maximum number of files to return

        Returns:
            str: JSON string with file metadata (name, type, modified date)
        """
        return await asyncio.to_thread(self.list_files, query=query, page_size=page_size)

    @authenticate
    def search_files(self, query: Optional[str] = None, max_results: int = 10) -> str:
        """
        Search Google Drive using a Drive query expression. Use for precise filtering
        such as ``name contains 'budget'`` or ``mimeType = 'application/pdf'``.

        Args:
            query (str): Drive query expression (see instructions for syntax)
            max_results (int): Maximum number of files to return

        Returns:
            str: JSON string with matching files and metadata
        """
        if max_results < 1:
            return json.dumps({"error": "max_results must be greater than 0"})

        try:
            service = cast(Resource, self.service)
            # Drive API includes trashed files by default — exclude them unless caller handles it
            if not query:
                effective_query = "trashed=false"
            elif "trashed=" in query.lower() or "trashed =" in query.lower():
                effective_query = query
            else:
                effective_query = f"({query}) and trashed=false"
            results = (
                service.files()
                .list(
                    q=effective_query,
                    pageSize=max_results,
                    orderBy="modifiedTime desc",
                    fields=self.SEARCH_FIELDS,
                )
                .execute()
            )
            files = results.get("files", [])
            return json.dumps(
                {
                    "query": effective_query,
                    "files": files,
                    "count": len(files),
                    "nextPageToken": results.get("nextPageToken"),
                }
            )
        except HttpError as e:
            return json.dumps({"error": f"Google Drive API error: {e}"})
        except Exception as e:
            log_error(f"Could not search Google Drive files: {e}")
            return json.dumps({"error": f"Unexpected error: {type(e).__name__}: {e}"})

    async def asearch_files(self, query: Optional[str] = None, max_results: int = 10) -> str:
        """
        Search Google Drive using a Drive query expression (async).

        Args:
            query (str): Drive query expression (see instructions for syntax)
            max_results (int): Maximum number of files to return

        Returns:
            str: JSON string with matching files and metadata
        """
        return await asyncio.to_thread(self.search_files, query=query, max_results=max_results)

    @authenticate
    def get_file_metadata(self, file_id: str) -> str:
        """
        Get detailed metadata for a Drive file by ID without reading or downloading its contents.

        Args:
            file_id (str): The Drive file ID

        Returns:
            str: JSON string with name, mimeType, size, owners, shared status, webViewLink
        """
        try:
            metadata = self._get_file_metadata(file_id, self.METADATA_FIELDS)
            return json.dumps(metadata)
        except HttpError as e:
            return json.dumps({"error": f"Google Drive API error: {e}"})
        except Exception as e:
            log_error(f"Could not get Google Drive metadata for {file_id}: {e}")
            return json.dumps({"error": f"Unexpected error: {type(e).__name__}: {e}"})

    async def aget_file_metadata(self, file_id: str) -> str:
        """
        Get detailed metadata for a Drive file by ID (async).

        Args:
            file_id (str): The Drive file ID

        Returns:
            str: JSON string with name, mimeType, size, owners, shared status, webViewLink
        """
        return await asyncio.to_thread(self.get_file_metadata, file_id)

    @authenticate
    def read_file(self, file_id: str) -> str:
        """
        Read a Drive file and return its text content in JSON for analysis or summarization.
        Docs and Slides are exported as plain text, Sheets as CSV, Scripts as JSON.
        For binary files (images, videos), use download_file instead.

        Args:
            file_id (str): The Drive file ID

        Returns:
            str: JSON string with file metadata and text content
        """
        try:
            service = cast(Resource, self.service)
            metadata = self._get_file_metadata(file_id, self.READ_METADATA_FIELDS)
            mime_type = metadata.get("mimeType", "")

            # Resolve text export format — known Workspace > unsupported Workspace > regular file
            if mime_type in self.TEXT_EXPORT_TYPES:
                export_mime = self.TEXT_EXPORT_TYPES[mime_type]
            elif WorkspaceType.is_workspace(mime_type):
                # Drawings, Vids, etc. have no text export — get_media() would crash
                return json.dumps(
                    {"error": f"Cannot read {mime_type} as text. Use download_file instead.", "file": metadata}
                )
            else:
                export_mime = None

            if export_mime:
                request = service.files().export_media(fileId=file_id, mimeType=export_mime)
                content_bytes = self._download_bytes(request)
                # Google Drive API hard limit on Workspace file exports
                if len(content_bytes) > 10 * 1024 * 1024:
                    return json.dumps({"error": "Export exceeds the 10 MB Drive limit.", "file": metadata})
            else:
                request = service.files().get_media(fileId=file_id)
                content_bytes = self._download_bytes(request)

            content = content_bytes.decode("utf-8", errors="replace")
            return json.dumps(
                {
                    "file": metadata,
                    "content": content,
                    "contentLength": len(content),
                    "exportMimeType": export_mime,
                }
            )
        except HttpError as e:
            return json.dumps({"error": f"Google Drive API error: {e}"})
        except Exception as e:
            log_error(f"Could not read Google Drive file {file_id}: {e}")
            return json.dumps({"error": f"Unexpected error: {type(e).__name__}: {e}"})

    async def aread_file(self, file_id: str) -> str:
        """
        Read a Drive file and return its text content in JSON (async).
        For binary files (images, videos), use download_file instead.

        Args:
            file_id (str): The Drive file ID

        Returns:
            str: JSON string with file metadata and text content
        """
        return await asyncio.to_thread(self.read_file, file_id)

    @authenticate
    def upload_file(self, file_path: Union[str, Path], mime_type: Optional[str] = None) -> str:
        """
        Upload a local file from disk to Google Drive as a new file.

        Args:
            file_path (str): Local filesystem path to the file to upload
            mime_type (str): MIME type override, inferred from file name if omitted

        Returns:
            str: JSON string with uploaded file metadata (id, name, webViewLink)
        """
        path = Path(file_path)
        if not path.exists() or not path.is_file():
            return json.dumps({"error": f"The file '{path}' does not exist or is not a file."})

        resolved_mime_type = mime_type
        if resolved_mime_type is None:
            resolved_mime_type, _ = mimetypes.guess_type(path.as_posix())
            if resolved_mime_type is None:
                resolved_mime_type = "application/octet-stream"

        try:
            service = cast(Resource, self.service)
            uploaded_file = (
                service.files()
                .create(
                    body={"name": path.name},
                    media_body=MediaFileUpload(path.as_posix(), mimetype=resolved_mime_type),
                    fields="id,name,mimeType,modifiedTime,size,webViewLink",
                )
                .execute()
            )
            return json.dumps(uploaded_file)
        except HttpError as e:
            return json.dumps({"error": f"Google Drive API error: {e}"})
        except Exception as e:
            log_error(f"Could not upload file '{path}': {e}")
            return json.dumps({"error": f"Unexpected error: {type(e).__name__}: {e}"})

    async def aupload_file(self, file_path: Union[str, Path], mime_type: Optional[str] = None) -> str:
        """
        Upload a local file from disk to Google Drive (async).

        Args:
            file_path (str): Local filesystem path to the file to upload
            mime_type (str): MIME type override, inferred from file name if omitted

        Returns:
            str: JSON string with uploaded file metadata (id, name, webViewLink)
        """
        return await asyncio.to_thread(self.upload_file, file_path, mime_type=mime_type)

    @authenticate
    def download_file(self, file_id: str, dest_path: Union[str, Path], export_format: Optional[str] = None) -> str:
        """
        Download a Drive file and save it to a local path on disk.
        Use when the user wants a local copy or a binary file (image, video, PDF).
        Workspace files are auto-exported to native formats (docx, xlsx, pptx, png).

        Args:
            file_id (str): The Drive file ID
            dest_path (str): Local destination path to save the file
            export_format (str): Optional MIME type to override the default export format

        Returns:
            str: JSON string with saved file path and download status
        """
        try:
            service = cast(Resource, self.service)
            path = Path(dest_path)
            metadata = self._get_file_metadata(file_id, "id,name,mimeType")
            mime_type = metadata.get("mimeType", "")

            # Resolve export target — user override > auto-detect > None for regular files
            if export_format:
                target_mime = export_format
                ext = mimetypes.guess_extension(export_format) or ""
            elif mime_type in self.DOWNLOAD_EXPORT_TYPES:
                target_mime, ext = self.DOWNLOAD_EXPORT_TYPES[mime_type]
            elif WorkspaceType.is_workspace(mime_type):
                # Future-proofing: catch new Workspace types Google may add
                return json.dumps({"error": f"Unsupported Workspace file type for download: {mime_type}"})
            else:
                target_mime = None
                ext = ""

            if not path.suffix and ext:
                path = path.with_suffix(ext)
            path.parent.mkdir(parents=True, exist_ok=True)

            if target_mime:
                # Workspace file — export to target format
                request = service.files().export_media(fileId=file_id, mimeType=target_mime)
                path.write_bytes(self._download_bytes(request))
                return json.dumps(
                    {
                        "fileId": file_id,
                        "path": str(path),
                        "status": "exported",
                        "exportMimeType": target_mime,
                        "originalMimeType": mime_type,
                    }
                )

            # Regular file — direct download
            request = service.files().get_media(fileId=file_id)
            with path.open("wb") as file_handle:
                downloader = MediaIoBaseDownload(file_handle, request)
                done = False
                while not done:
                    _, done = downloader.next_chunk()
            return json.dumps({"fileId": file_id, "path": str(path), "status": "downloaded"})
        except HttpError as e:
            return json.dumps({"error": f"Google Drive API error: {e}"})
        except Exception as e:
            log_error(f"Could not download file '{file_id}': {e}")
            return json.dumps({"error": f"Unexpected error: {type(e).__name__}: {e}"})

    async def adownload_file(
        self, file_id: str, dest_path: Union[str, Path], export_format: Optional[str] = None
    ) -> str:
        """
        Download a Drive file and save it to a local path on disk (async).
        Workspace files are auto-exported to native formats.

        Args:
            file_id (str): The Drive file ID
            dest_path (str): Local destination path to save the file
            export_format (str): Optional MIME type to override the default export format

        Returns:
            str: JSON string with saved file path and download status
        """
        return await asyncio.to_thread(self.download_file, file_id, dest_path, export_format=export_format)
