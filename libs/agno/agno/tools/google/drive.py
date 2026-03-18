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


DRIVE_QUERY_INSTRUCTIONS = textwrap.dedent("""\
    You have access to Google Drive tools for searching, reading, uploading, and downloading files.

    ## Drive Query Syntax
    Use these operators in search and list query parameters:
    - `name contains 'report'` — files with "report" in the name
    - `name = 'Budget 2025.xlsx'` — exact name match
    - `mimeType = 'application/vnd.google-apps.document'` — Google Docs only
    - `mimeType = 'application/vnd.google-apps.spreadsheet'` — Google Sheets only
    - `mimeType = 'application/pdf'` — PDF files only
    - `mimeType = 'application/vnd.google-apps.folder'` — folders only
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
                if creds_to_use is None:
                    raise ValueError("Google Drive credentials are not available.")
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

    DEFAULT_SCOPES = {
        "read": "https://www.googleapis.com/auth/drive.readonly",
        "write": "https://www.googleapis.com/auth/drive.file",
        "full": "https://www.googleapis.com/auth/drive",
    }

    # Workspace types exportable to text; others return an error
    EXPORT_MIME_TYPES = {
        "application/vnd.google-apps.document": "text/plain",
        "application/vnd.google-apps.spreadsheet": "text/csv",
        "application/vnd.google-apps.presentation": "text/plain",
    }

    METADATA_FIELDS = "id,name,mimeType,modifiedTime,size,owners,shared,webViewLink"
    SEARCH_FIELDS = "nextPageToken, files(id, name, mimeType, modifiedTime, size, owners(displayName, emailAddress))"
    READ_METADATA_FIELDS = "id,name,mimeType,modifiedTime,size,webViewLink"
    EXPORT_LIMIT_BYTES = 10 * 1024 * 1024

    service: Optional[Resource]

    def __init__(
        self,
        auth_port: Optional[int] = 5050,
        login_hint: Optional[str] = None,
        creds: Optional[Union[Credentials, ServiceAccountCredentials]] = None,
        scopes: Optional[List[str]] = None,
        creds_path: Optional[str] = None,
        token_path: Optional[str] = None,
        service_account_path: Optional[str] = None,
        service_account_file: Optional[str] = None,
        delegated_user: Optional[str] = None,
        quota_project_id: Optional[str] = None,
        max_content_length: Optional[int] = 10000,
        list_files: bool = True,
        search_files: bool = True,
        get_file_metadata: bool = True,
        read_file: bool = True,
        upload_file: bool = False,
        download_file: bool = False,
        instructions: Optional[str] = None,
        add_instructions: bool = True,
        **kwargs,
    ):
        """Initialize GoogleDriveTools.

        Args:
            auth_port: Port for the OAuth local server redirect. Defaults to 5050.
            login_hint: Email to pre-select in the OAuth consent screen.
            creds: Pre-fetched credentials. Defaults to None.
            scopes: Custom OAuth scopes. If None, inferred from enabled tools.
            creds_path: Path to OAuth client credentials JSON file.
            token_path: Path to the cached OAuth token file.
            service_account_path: Path to a Google service account JSON key file.
            service_account_file: Alias for service_account_path.
            delegated_user: User email to impersonate via domain-wide delegation (optional for Drive).
            quota_project_id: Google Cloud quota project ID. Falls back to GOOGLE_CLOUD_QUOTA_PROJECT_ID env var.
            max_content_length: Max characters returned by read_file. None for unlimited. Defaults to 10000.
            list_files: Enable the list_files tool.
            search_files: Enable the search_files tool.
            get_file_metadata: Enable the get_file_metadata tool.
            read_file: Enable the read_file tool.
            upload_file: Enable the upload_file tool. Disabled by default.
            download_file: Enable the download_file tool. Disabled by default.
            instructions: Custom instructions for the toolkit. If None, uses DRIVE_QUERY_INSTRUCTIONS.
            add_instructions: Whether to inject toolkit instructions into the agent system prompt.
        """
        if instructions is None:
            self.instructions = DRIVE_QUERY_INSTRUCTIONS
        else:
            self.instructions = instructions

        self.creds = creds
        self.service = None
        self.credentials_path = creds_path
        self.token_path = token_path
        self.service_account_path = service_account_path or service_account_file
        self.delegated_user = delegated_user
        self.login_hint = login_hint
        self.quota_project_id = quota_project_id or getenv("GOOGLE_CLOUD_QUOTA_PROJECT_ID")
        self.max_content_length = max_content_length

        if self.max_content_length is not None and self.max_content_length < 1:
            raise ValueError("max_content_length must be greater than 0 when provided")

        auth_port_value = getenv("GOOGLE_AUTH_PORT", getenv("GOOGLE_AUTHENTICATION_PORT", str(auth_port or 0)))
        self.auth_port = int(auth_port_value)

        read_tools_enabled = any([list_files, search_files, get_file_metadata, read_file, download_file])

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

        read_scope_candidates = {
            self.DEFAULT_SCOPES["read"],
            self.DEFAULT_SCOPES["write"],
            self.DEFAULT_SCOPES["full"],
        }
        write_scope_candidates = {
            self.DEFAULT_SCOPES["write"],
            self.DEFAULT_SCOPES["full"],
        }

        if read_tools_enabled and not any(scope in self.scopes for scope in read_scope_candidates):
            raise ValueError(
                "A Google Drive read scope is required for list_files, search_files, "
                "get_file_metadata, read_file, or download_file"
            )
        if upload_file and not any(scope in self.scopes for scope in write_scope_candidates):
            raise ValueError("A Google Drive write scope is required for upload_file")

        tools: List[Any] = []
        async_tools: List[Tuple[Any, str]] = []

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

    def _normalize_query(self, query: Optional[str]) -> str:
        """Auto-append trashed=false unless the caller already filters on trashed."""
        if not query:
            return "trashed=false"
        if "trashed" in query.lower():
            return query
        return f"({query}) and trashed=false"

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

    def _truncate_content(self, content: str) -> Tuple[str, bool]:
        """Truncate to max_content_length if configured."""
        if self.max_content_length is None or len(content) <= self.max_content_length:
            return content, False
        return content[: self.max_content_length], True

    async def _run_in_executor(self, func: Any, *args: Any, **kwargs: Any) -> str:
        """Run a synchronous tool method in the default executor for async support."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, partial(func, *args, **kwargs))

    def list_files(self, query: Optional[str] = None, page_size: int = 10) -> str:
        """List files in Google Drive. Delegates to search_files.

        Args:
            query: Optional Google Drive query string to filter files.
            page_size: Maximum number of files to return.

        Returns:
            str: JSON string containing matching files and the effective query.
        """
        return self.search_files(query=query, max_results=page_size)

    async def alist_files(self, query: Optional[str] = None, page_size: int = 10) -> str:
        """List files in Google Drive (async). Delegates to search_files.

        Args:
            query: Optional Google Drive query string to filter files.
            page_size: Maximum number of files to return.

        Returns:
            str: JSON string containing matching files and the effective query.
        """
        return await self._run_in_executor(self.list_files, query=query, page_size=page_size)

    @authenticate
    def search_files(self, query: Optional[str] = None, max_results: int = 10) -> str:
        """Search Google Drive files using Drive query syntax.

        Args:
            query: Drive query expression for files().list(). Examples:
                - ``name contains 'report'``
                - ``mimeType='application/vnd.google-apps.document'``
                - ``modifiedTime > '2025-01-01T00:00:00'``
                - ``'<folder_id>' in parents``
                Combine clauses with ``and`` / ``or``. ``trashed=false`` is added
                automatically unless you include a trashed clause.
            max_results: Maximum number of files to return.

        Returns:
            str: JSON string with keys: query, files, count, nextPageToken.
        """
        if max_results < 1:
            return json.dumps({"error": "max_results must be greater than 0"})

        try:
            service = cast(Resource, self.service)
            effective_query = self._normalize_query(query)
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
            query: Drive query expression for files().list(). Examples:
                - ``name contains 'report'``
                - ``mimeType='application/vnd.google-apps.document'``
                - ``modifiedTime > '2025-01-01T00:00:00'``
                - ``'<folder_id>' in parents``
                Combine clauses with ``and`` / ``or``. ``trashed=false`` is added
                automatically unless you include a trashed clause.
            max_results: Maximum number of files to return.

        Returns:
            str: JSON string with keys: query, files, count, nextPageToken.
        """
        return await self._run_in_executor(self.search_files, query=query, max_results=max_results)

    @authenticate
    def get_file_metadata(self, file_id: str) -> str:
        """Get metadata for a Google Drive file.

        Args:
            file_id: The Drive file ID.

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
            file_id: The Drive file ID.

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

        Other files are downloaded directly and decoded as text.
        Content is truncated to max_content_length (default 10000 chars).

        Args:
            file_id: The Drive file ID.

        Returns:
            str: JSON string with keys: file (metadata), content, truncated,
                contentLength, returnedContentLength, readMethod, exportMimeType.
        """
        try:
            service = cast(Resource, self.service)
            metadata = self._get_file_metadata_internal(file_id, self.READ_METADATA_FIELDS)
            mime_type = metadata.get("mimeType", "")
            export_mime_type = None
            read_method = "download"

            if mime_type in self.EXPORT_MIME_TYPES:
                export_mime_type = self.EXPORT_MIME_TYPES[mime_type]
                # export_media() supports chunked download via MediaIoBaseDownload
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
            elif mime_type.startswith("application/vnd.google-apps."):
                return json.dumps(
                    {
                        "error": f"Unsupported Google Workspace file type for read_file: {mime_type}",
                        "file": metadata,
                    }
                )
            else:
                request = service.files().get_media(fileId=file_id)
                content_bytes = self._download_bytes(request)

            decoded_content = self._decode_file_content(content_bytes)
            truncated_content, truncated = self._truncate_content(decoded_content)
            return json.dumps(
                {
                    "file": metadata,
                    "content": truncated_content,
                    "truncated": truncated,
                    "contentLength": len(decoded_content),
                    "returnedContentLength": len(truncated_content),
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
            file_id: The Drive file ID.

        Returns:
            str: JSON string with file metadata, content, and truncation details.
        """
        return await self._run_in_executor(self.read_file, file_id)

    @authenticate
    def upload_file(self, file_path: Union[str, Path], mime_type: Optional[str] = None) -> str:
        """Upload a local file to Google Drive.

        Args:
            file_path: Local path to the file to upload.
            mime_type: MIME type override. If omitted, inferred from the file name.

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
            file_path: Local path to the file to upload.
            mime_type: MIME type override. If omitted, inferred from the file name.

        Returns:
            str: JSON string containing metadata for the uploaded file.
        """
        return await self._run_in_executor(self.upload_file, file_path, mime_type=mime_type)

    @authenticate
    def download_file(self, file_id: str, dest_path: Union[str, Path]) -> str:
        """Download a file from Google Drive to a local path.

        Args:
            file_id: The Drive file ID.
            dest_path: Local destination path for the downloaded file.

        Returns:
            str: JSON string confirming the download with fileId, path, and status.
        """
        path = Path(dest_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        try:
            service = cast(Resource, self.service)
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

    async def adownload_file(self, file_id: str, dest_path: Union[str, Path]) -> str:
        """Download a file from Google Drive to a local path (async).

        Args:
            file_id: The Drive file ID.
            dest_path: Local destination path for the downloaded file.

        Returns:
            str: JSON string confirming the download.
        """
        return await self._run_in_executor(self.download_file, file_id, dest_path)
