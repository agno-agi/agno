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
from functools import partial, wraps
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
    """Decorator to ensure authentication before executing a function."""

    @wraps(func)
    def wrapper(self, *args, **kwargs):
        try:
            if not self.creds or not self.creds.valid:
                self._auth()
            if not self.service:
                creds_to_use = self.creds
                if self.quota_project_id and hasattr(creds_to_use, "with_quota_project"):
                    creds_to_use = cast(Any, creds_to_use).with_quota_project(self.quota_project_id)
                self.service = build("drive", "v3", credentials=creds_to_use)
        except Exception as e:
            log_error(f"Google Drive authentication failed: {e}")
            return json.dumps({"error": f"Google Drive authentication failed: {e}"})
        return func(self, *args, **kwargs)

    return wrapper


class GoogleDriveTools(Toolkit):
    """Google Drive toolkit for searching, reading, uploading, and downloading files.

    Provides tools for agents to interact with Google Drive:
    - search_files: Search files using Drive query syntax
    - read_file: Read Google Docs/Sheets/Slides as text, or download regular files
    - get_file_metadata: Get metadata for a file
    - list_files: Backward-compatible wrapper around search_files
    - upload_file: Upload a local file to Drive
    - download_file: Download a Drive file locally
    """

    # Keyed by access level; auto-inferred from enabled tools when scopes=None
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
    # Google Drive API hard limit on Workspace file exports
    EXPORT_LIMIT_BYTES = 10 * 1024 * 1024

    service: Optional[Resource]

    def __init__(
        self,
        # Authentication
        auth_port: Optional[int] = 5050,
        login_hint: Optional[str] = None,
        creds: Optional[Union[Credentials, ServiceAccountCredentials]] = None,
        scopes: Optional[List[str]] = None,
        creds_path: Optional[str] = None,
        token_path: Optional[str] = None,
        # Service account auth — alternative to OAuth for server/bot deployments
        service_account_path: Optional[str] = None,
        service_account_file: Optional[str] = None,
        # Optional for Drive (unlike Gmail which requires it for mailbox access)
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

        # Env vars override constructor arg; supports legacy GOOGLE_AUTHENTICATION_PORT
        auth_port_value = getenv("GOOGLE_AUTH_PORT", getenv("GOOGLE_AUTHENTICATION_PORT", str(auth_port or 0)))
        self.auth_port = int(auth_port_value)

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

        # Any of these scopes grant read access; drive.file only covers app-created files
        read_scope_candidates = {
            self.DEFAULT_SCOPES["read"],
            self.DEFAULT_SCOPES["write"],
            self.DEFAULT_SCOPES["full"],
        }
        write_scope_candidates = {
            self.DEFAULT_SCOPES["write"],
            self.DEFAULT_SCOPES["full"],
        }

        # Validate custom scopes match enabled tools
        if read_tools_enabled and not any(scope in self.scopes for scope in read_scope_candidates):
            raise ValueError(
                "A Google Drive read scope is required for list_files, search_files, "
                "get_file_metadata, read_file, or download_file"
            )
        if upload_file and not any(scope in self.scopes for scope in write_scope_candidates):
            raise ValueError("A Google Drive write scope is required for upload_file")

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
            # Drive doesn't require delegated_user (unlike Gmail)
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

    def _get_file_metadata_internal(self, file_id: str, fields: str) -> dict:
        """Shared metadata fetch used by get_file_metadata and read_file."""
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

    def _decode_file_content(self, content_bytes: bytes) -> str:
        """Multi-encoding decode chain for raw file bytes."""
        for encoding in ("utf-8-sig", "utf-16", "utf-16-le", "utf-16-be"):
            try:
                return content_bytes.decode(encoding)
            except UnicodeDecodeError:
                continue
        return content_bytes.decode("utf-8", errors="replace")

    async def _run_in_executor(self, func: Any, *args: Any, **kwargs: Any) -> str:
        """Run a synchronous tool method in the default executor for async support."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, partial(func, *args, **kwargs))

    def list_files(self, query: Optional[str] = None, page_size: int = 10) -> str:
        """List files in Google Drive. Delegates to search_files.

        Args:
            query (str): Optional Google Drive query string to filter files.
            page_size (int): Maximum number of files to return.

        Returns:
            str: JSON string containing matching files and the effective query.
        """
        return self.search_files(query=query, max_results=page_size)

    async def alist_files(self, query: Optional[str] = None, page_size: int = 10) -> str:
        """List files in Google Drive (async). Delegates to search_files.

        Args:
            query (str): Optional Google Drive query string to filter files.
            page_size (int): Maximum number of files to return.

        Returns:
            str: JSON string containing matching files and the effective query.
        """
        return await self._run_in_executor(self.list_files, query=query, page_size=page_size)

    @authenticate
    def search_files(self, query: Optional[str] = None, max_results: int = 10) -> str:
        """Search Google Drive files using Drive query syntax.

        Args:
            query (str): Drive query expression for files().list(). Examples:
                - ``name contains 'report'``
                - ``mimeType='application/vnd.google-apps.document'``
                - ``modifiedTime > '2025-01-01T00:00:00'``
                - ``'<folder_id>' in parents``
                Combine clauses with ``and`` / ``or``. ``trashed=false`` is added
                automatically unless you include a trashed clause.
            max_results (int): Maximum number of files to return.

        Returns:
            str: JSON string with keys: query, files, count, nextPageToken.
        """
        if max_results < 1:
            return json.dumps({"error": "max_results must be greater than 0"})

        try:
            service = cast(Resource, self.service)
            # Auto-append trashed=false unless caller already filters on trashed
            if not query:
                effective_query = "trashed=false"
            elif "trashed" in query.lower():
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
        """Search Google Drive files using Drive query syntax (async).

        Args:
            query (str): Drive query expression for files().list(). Examples:
                - ``name contains 'report'``
                - ``mimeType='application/vnd.google-apps.document'``
                - ``modifiedTime > '2025-01-01T00:00:00'``
                - ``'<folder_id>' in parents``
                Combine clauses with ``and`` / ``or``. ``trashed=false`` is added
                automatically unless you include a trashed clause.
            max_results (int): Maximum number of files to return.

        Returns:
            str: JSON string with keys: query, files, count, nextPageToken.
        """
        return await self._run_in_executor(self.search_files, query=query, max_results=max_results)

    @authenticate
    def get_file_metadata(self, file_id: str) -> str:
        """Get metadata for a Google Drive file.

        Args:
            file_id (str): The Drive file ID.

        Returns:
            str: JSON string containing file metadata (id, name, mimeType, modifiedTime,
                size, owners, shared, webViewLink).
        """
        try:
            metadata = self._get_file_metadata_internal(file_id, self.METADATA_FIELDS)
            return json.dumps(metadata)
        except HttpError as e:
            return json.dumps({"error": f"Google Drive API error: {e}"})
        except Exception as e:
            log_error(f"Could not get Google Drive metadata for {file_id}: {e}")
            return json.dumps({"error": f"Unexpected error: {type(e).__name__}: {e}"})

    async def aget_file_metadata(self, file_id: str) -> str:
        """Get metadata for a Google Drive file (async).

        Args:
            file_id (str): The Drive file ID.

        Returns:
            str: JSON string containing file metadata.
        """
        return await self._run_in_executor(self.get_file_metadata, file_id)

    @authenticate
    def read_file(self, file_id: str) -> str:
        """Read a Google Drive file as text.

        Google Workspace files are exported to text formats:
        - Docs -> plain text
        - Sheets -> CSV (first sheet only, Google API limitation)
        - Slides -> plain text
        - Apps Script -> JSON

        Other Workspace types (Drawings, Vids) cannot be read as text —
        use download_file instead. Regular files are downloaded and decoded.
        Args:
            file_id (str): The Drive file ID.

        Returns:
            str: JSON string with keys: file (metadata), content,
                contentLength, readMethod, exportMimeType.
        """
        try:
            service = cast(Resource, self.service)
            metadata = self._get_file_metadata_internal(file_id, self.READ_METADATA_FIELDS)
            mime_type = metadata.get("mimeType", "")
            export_mime_type = None
            read_method = "download"

            if mime_type in self.TEXT_EXPORT_TYPES:
                export_mime_type = self.TEXT_EXPORT_TYPES[mime_type]
                request = service.files().export_media(fileId=file_id, mimeType=export_mime_type)
                content_bytes = self._download_bytes(request)
                read_method = "export"
                if len(content_bytes) > self.EXPORT_LIMIT_BYTES:
                    return json.dumps(
                        {
                            "error": "Exported Google Workspace content exceeds the 10 MB Drive export limit.",
                            "file": metadata,
                            "exportMimeType": export_mime_type,
                        }
                    )
            elif WorkspaceType.is_workspace(mime_type):
                return json.dumps(
                    {
                        "error": f"Cannot read {mime_type} as text. Use download_file instead.",
                        "file": metadata,
                    }
                )
            else:
                request = service.files().get_media(fileId=file_id)
                content_bytes = self._download_bytes(request)

            content = self._decode_file_content(content_bytes)
            return json.dumps(
                {
                    "file": metadata,
                    "content": content,
                    "contentLength": len(content),
                    "readMethod": read_method,
                    "exportMimeType": export_mime_type,
                }
            )
        except HttpError as e:
            error_text = str(e).lower()
            if "cannotexportfile" in error_text or "exportsizelimitexceeded" in error_text:
                return json.dumps(
                    {
                        "error": (
                            "Google Drive could not export this file. Google Workspace exports are limited to 10 MB."
                        )
                    }
                )
            return json.dumps({"error": f"Google Drive API error: {e}"})
        except Exception as e:
            log_error(f"Could not read Google Drive file {file_id}: {e}")
            return json.dumps({"error": f"Unexpected error: {type(e).__name__}: {e}"})

    async def aread_file(self, file_id: str) -> str:
        """Read a Google Drive file as text (async).

        Google Workspace files are exported to text formats:
        - Docs -> plain text
        - Sheets -> CSV (first sheet only, Google API limitation)
        - Slides -> plain text

        Other files are downloaded directly and decoded as text.

        Args:
            file_id (str): The Drive file ID.

        Returns:
            str: JSON string with file metadata and content.
        """
        return await self._run_in_executor(self.read_file, file_id)

    @authenticate
    def upload_file(self, file_path: Union[str, Path], mime_type: Optional[str] = None) -> str:
        """Upload a local file to Google Drive.

        Args:
            file_path (str): Local path to the file to upload.
            mime_type (str): MIME type override. If omitted, inferred from the file name.

        Returns:
            str: JSON string containing metadata for the uploaded file.
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
        """Upload a local file to Google Drive (async).

        Args:
            file_path (str): Local path to the file to upload.
            mime_type (str): MIME type override. If omitted, inferred from the file name.

        Returns:
            str: JSON string containing metadata for the uploaded file.
        """
        return await self._run_in_executor(self.upload_file, file_path, mime_type=mime_type)

    @authenticate
    def download_file(self, file_id: str, dest_path: Union[str, Path], export_format: Optional[str] = None) -> str:
        """Download a file from Google Drive to a local path.

        Regular files are downloaded directly. Google Workspace files (Docs,
        Sheets, Slides, Drawings, Apps Script, Vids) are automatically exported
        to the best native format (docx, xlsx, pptx, png, json, mp4).

        Args:
            file_id (str): The Drive file ID.
            dest_path (str): Local destination path for the downloaded file.
            export_format (str): Optional MIME type override for Workspace file export
                (e.g. 'application/pdf' to download a Google Doc as PDF).

        Returns:
            str: JSON string with fileId, path, status ("downloaded" or "exported"),
                and exportMimeType/originalMimeType for exported files.
        """
        try:
            service = cast(Resource, self.service)
            path = Path(dest_path)
            metadata = self._get_file_metadata_internal(file_id, "id,name,mimeType")
            mime_type = metadata.get("mimeType", "")

            if export_format:
                # User override — export to specified format
                ext = mimetypes.guess_extension(export_format) or ""
                if not path.suffix:
                    path = path.with_suffix(ext)
                path.parent.mkdir(parents=True, exist_ok=True)
                request = service.files().export_media(fileId=file_id, mimeType=export_format)
                path.write_bytes(self._download_bytes(request))
                return json.dumps(
                    {
                        "fileId": file_id,
                        "path": str(path),
                        "status": "exported",
                        "exportMimeType": export_format,
                        "originalMimeType": mime_type,
                    }
                )

            if mime_type in self.DOWNLOAD_EXPORT_TYPES:
                # Known Workspace type — auto-export to best format
                target_mime, ext = self.DOWNLOAD_EXPORT_TYPES[mime_type]
                if not path.suffix:
                    path = path.with_suffix(ext)
                path.parent.mkdir(parents=True, exist_ok=True)
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

            if WorkspaceType.is_workspace(mime_type):
                # Unknown Workspace type — no known export format
                return json.dumps({"error": f"Unsupported Workspace file type for download: {mime_type}"})

            # Regular file — direct download
            path.parent.mkdir(parents=True, exist_ok=True)
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
        """Download a file from Google Drive to a local path (async).

        Regular files are downloaded directly. Google Workspace files are
        automatically exported to the best native format.

        Args:
            file_id (str): The Drive file ID.
            dest_path (str): Local destination path for the downloaded file.
            export_format (str): Optional MIME type override for Workspace file export.

        Returns:
            str: JSON string with download/export details.
        """
        return await self._run_in_executor(self.download_file, file_id, dest_path, export_format=export_format)
