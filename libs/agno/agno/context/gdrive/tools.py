"""
Drive toolkit that actually sees shared folders and Shared Drives.

The upstream ``GoogleDriveTools.search_files`` / ``_get_file_metadata`` /
``read_file`` methods don't pass ``corpora="allDrives"``,
``includeItemsFromAllDrives=True``, or ``supportsAllDrives=True``. That
defaults the Drive API to ``corpora=user``, which for a service account
means "files directly owned by the SA" — nothing shared with it and
nothing in Shared Drives. So a standard service-account setup (SA +
folders shared by humans + files in Shared Drives) returns zero hits
for the most ordinary ``name contains 'X'`` query.

This subclass overrides the three call sites and injects the allDrives
triple on every request. Everything else (auth, ``include_trashed``,
field selection, error handling) is inherited unchanged.

Kept local to ``agno.context.gdrive`` instead of fixing upstream so
callers of ``GoogleDriveTools`` directly aren't affected by the scope
change.
"""

from __future__ import annotations

import io
import json
from typing import Any, Optional, cast

from agno.tools.google.drive import GoogleDriveTools, WorkspaceType, authenticate
from agno.utils.log import log_error

try:
    from googleapiclient.discovery import Resource
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaIoBaseDownload
except ImportError:
    raise ImportError(
        "Google client library for Python not found, install it using "
        "`pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib`"
    )


class AllDrivesGoogleDriveTools(GoogleDriveTools):
    """Drive toolkit that searches personal + shared + Shared Drive corpora."""

    @authenticate
    def search_files(self, query: Optional[str] = None, max_results: int = 10, page_token: Optional[str] = None) -> str:
        if max_results < 1:
            return json.dumps({"error": "max_results must be greater than 0"})
        try:
            service = cast(Resource, self.service)
            if self.include_trashed:
                effective_query = query or ""
            elif query:
                effective_query = f"({query}) and trashed=false"
            else:
                effective_query = "trashed=false"
            list_kwargs: dict = {
                "q": effective_query,
                "pageSize": max_results,
                "orderBy": "modifiedTime desc",
                "fields": self.SEARCH_FIELDS,
                "corpora": "allDrives",
                "includeItemsFromAllDrives": True,
                "supportsAllDrives": True,
            }
            if page_token:
                list_kwargs["pageToken"] = page_token
            results = service.files().list(**list_kwargs).execute()
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

    def _get_file_metadata(self, file_id: str, fields: str) -> dict:
        service = cast(Resource, self.service)
        return service.files().get(fileId=file_id, fields=fields, supportsAllDrives=True).execute()

    @authenticate
    def read_file(self, file_id: str) -> str:
        try:
            service = cast(Resource, self.service)
            metadata = self._get_file_metadata(file_id, self.READ_METADATA_FIELDS)
            mime_type = metadata.get("mimeType", "")

            if mime_type in self.TEXT_EXPORT_TYPES:
                export_mime: Optional[str] = self.TEXT_EXPORT_TYPES[mime_type]
            elif mime_type.startswith(WorkspaceType.WORKSPACE_PREFIX):
                return json.dumps(
                    {"error": f"Cannot read {mime_type} as text. Use download_file instead.", "file": metadata}
                )
            else:
                export_mime = None

            if export_mime:
                request = service.files().export_media(fileId=file_id, mimeType=export_mime)
                content_bytes = _download_bytes(request)
            else:
                file_size = int(metadata.get("size", 0))
                if file_size > self.max_read_size:
                    return json.dumps(
                        {
                            "error": (
                                f"File is {file_size} bytes, exceeds max_read_size "
                                f"({self.max_read_size}). Use download_file instead."
                            ),
                            "file": metadata,
                        }
                    )
                request = service.files().get_media(fileId=file_id, supportsAllDrives=True)
                content_bytes = _download_bytes(request)

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


def _download_bytes(request: Any) -> bytes:
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buffer.getvalue()
