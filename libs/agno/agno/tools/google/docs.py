"""
Google Docs Toolset for interacting with Docs API

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
3. Enable the Google Docs API and Google Drive API:
   - Go to "APIs & Services" > "Enable APIs and Services"
   - Search for "Google Docs API" and "Google Drive API"
   - Click "Enable" for both

4. Create OAuth 2.0 credentials:
   - Go to "APIs & Services" > "Credentials"
   - Click "Create Credentials" > "OAuth client ID"
   - Go through the OAuth consent screen setup
   - Give it a name and click "Create"
   - You'll receive:
     * Client ID (GOOGLE_CLIENT_ID)
     * Client Secret (GOOGLE_CLIENT_SECRET)

5. Set up environment variables:
   Create a .envrc file in your project root with:
   ```
   export GOOGLE_CLIENT_ID=your_client_id_here
   export GOOGLE_CLIENT_SECRET=your_client_secret_here
   export GOOGLE_PROJECT_ID=your_project_id_here
   export GOOGLE_REDIRECT_URI=http://localhost
   ```

Alternatively, for Server-to-Server use cases you can use a Service Account:
   export GOOGLE_SERVICE_ACCOUNT_FILE=path/to/service-account.json
"""

import asyncio
import io
import json
import textwrap
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union, cast

try:
    from google.oauth2.credentials import Credentials
    from google.oauth2.service_account import Credentials as ServiceAccountCredentials
    from googleapiclient.discovery import Resource, build
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaIoBaseDownload
except ImportError:
    raise ImportError(
        "`google-api-python-client` `google-auth-httplib2` `google-auth-oauthlib` not installed. "
        "Please install using `pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib`"
    )

from agno.tools.google.auth import google_authenticate
from agno.tools.google.base import GoogleToolkit
from agno.utils.log import log_error

DOCS_INSTRUCTIONS = textwrap.dedent("""\
    You have access to Google Docs tools for creating, reading, and updating documents.

    ## Key Workflow
    - Call create_document to start a new doc; it returns documentId
    - Use get_document_text for simple reads; use get_document for structural editing
    - Use batch_update with structured requests for any document modification
    - Use append_text as a convenience to add content at the end of a document

    ## Tips
    - Document IDs come from the API or from doc URLs -- never invent them
    - batch_update is the workhorse: insertText, replaceAllText, updateTextStyle, deleteContentRange
    - export_as_pdf is off by default; when enabled it writes PDFs under the toolkit's
      export_dir sandbox (bare filenames only, path separators rejected). Original doc unchanged.
    - delete_document moves to Drive trash (recoverable for 30 days); off by default""")


authenticate = google_authenticate("docs")


class GoogleDocsTools(GoogleToolkit):
    api_name = "docs"
    api_version = "v1"
    google_service_name = "docs"
    default_scopes = [
        "https://www.googleapis.com/auth/documents",
        "https://www.googleapis.com/auth/drive.file",
    ]
    DEFAULT_SCOPES = default_scopes

    def __init__(
        self,
        oauth_config: Optional[Any] = None,
        store_token_in_db: bool = False,
        scopes: Optional[List[str]] = None,
        creds: Optional[Union[Credentials, ServiceAccountCredentials]] = None,
        credentials_path: Optional[str] = None,
        token_path: Optional[str] = None,
        service_account_path: Optional[str] = None,
        delegated_user: Optional[str] = None,
        oauth_port: int = 0,
        login_hint: Optional[str] = None,
        create_document: bool = True,
        get_document: bool = True,
        get_document_text: bool = True,
        batch_update: bool = True,
        append_text: bool = True,
        export_as_pdf: bool = False,
        export_dir: Union[str, Path] = Path("."),
        delete_document: bool = False,
        all: bool = False,
        instructions: Optional[str] = None,
        add_instructions: bool = True,
        **kwargs,
    ):
        self.export_dir = Path(export_dir).resolve()

        tools: List[Any] = []
        async_tools: List[Tuple[Any, str]] = []
        if all or create_document:
            tools.append(self.create_document)
            async_tools.append((self.acreate_document, "create_document"))
        if all or get_document:
            tools.append(self.get_document)
            async_tools.append((self.aget_document, "get_document"))
        if all or get_document_text:
            tools.append(self.get_document_text)
            async_tools.append((self.aget_document_text, "get_document_text"))
        if all or batch_update:
            tools.append(self.batch_update)
            async_tools.append((self.abatch_update, "batch_update"))
        if all or append_text:
            tools.append(self.append_text)
            async_tools.append((self.aappend_text, "append_text"))
        if all or export_as_pdf:
            tools.append(self.export_as_pdf)
            async_tools.append((self.aexport_as_pdf, "export_as_pdf"))
        if all or delete_document:
            tools.append(self.delete_document)
            async_tools.append((self.adelete_document, "delete_document"))

        if instructions is None:
            instructions = DOCS_INSTRUCTIONS

        super().__init__(
            name="google_docs_tools",
            tools=tools,
            async_tools=async_tools,
            instructions=instructions,
            add_instructions=add_instructions,
            scopes=scopes,
            creds=creds,
            token_path=token_path,
            credentials_path=credentials_path,
            service_account_path=service_account_path,
            delegated_user=delegated_user,
            oauth_config=oauth_config,
            store_token_in_db=store_token_in_db,
            oauth_port=oauth_port,
            login_hint=login_hint,
            **kwargs,
        )

    def _build_service(self, creds):
        return {
            "docs": build("docs", "v1", credentials=creds),
            "drive": build("drive", "v3", credentials=creds),
        }

    @property
    def docs_service(self) -> Any:
        svc = self.service
        return svc["docs"] if isinstance(svc, dict) else svc

    @property
    def drive_service(self) -> Any:
        svc = self.service
        return svc["drive"] if isinstance(svc, dict) else None

    def _extract_text_from_content(self, content: List[Dict[str, Any]]) -> str:
        parts: List[str] = []
        for element in content:
            paragraph = element.get("paragraph")
            if not paragraph:
                continue
            for run in paragraph.get("elements", []):
                text_run = run.get("textRun")
                if text_run and "content" in text_run:
                    parts.append(text_run["content"])
        return "".join(parts)

    @authenticate
    def create_document(self, title: str) -> str:
        """
        Create a new Google Doc.

        Args:
            title (str): The title for the new document.

        Returns:
            str: JSON string with documentId and title, or error message.
        """
        try:
            service = cast(Resource, self.docs_service)
            doc = service.documents().create(body={"title": title}).execute()
            return json.dumps(
                {
                    "documentId": doc.get("documentId"),
                    "title": doc.get("title"),
                    "url": f"https://docs.google.com/document/d/{doc.get('documentId')}/edit",
                }
            )
        except HttpError as e:
            return json.dumps({"error": f"Google Docs API error: {e}"})
        except Exception as e:
            log_error(f"Could not create document: {e}")
            return json.dumps({"error": f"Unexpected error: {type(e).__name__}: {e}"})

    async def acreate_document(self, title: str) -> str:
        """Create a new Google Doc (async)."""
        return await asyncio.to_thread(self.create_document, title=title)

    @authenticate
    def get_document(self, document_id: str) -> str:
        """
        Fetch the full JSON structure of a Google Doc.

        Use this when you need the body content with structural information
        (paragraphs, indices, styles). For plain text only, prefer get_document_text.

        Args:
            document_id (str): The ID of the document to fetch.

        Returns:
            str: JSON string of the full document structure, or error message.
        """
        try:
            service = cast(Resource, self.docs_service)
            doc = service.documents().get(documentId=document_id).execute()
            return json.dumps(doc)
        except HttpError as e:
            return json.dumps({"error": f"Google Docs API error: {e}"})
        except Exception as e:
            log_error(f"Could not get document {document_id}: {e}")
            return json.dumps({"error": f"Unexpected error: {type(e).__name__}: {e}"})

    async def aget_document(self, document_id: str) -> str:
        """Fetch the full JSON structure of a Google Doc (async)."""
        return await asyncio.to_thread(self.get_document, document_id=document_id)

    @authenticate
    def get_document_text(self, document_id: str) -> str:
        """
        Fetch a Google Doc and return only its plain text body.

        Args:
            document_id (str): The ID of the document to fetch.

        Returns:
            str: JSON string with documentId, title, and text, or error message.
        """
        try:
            service = cast(Resource, self.docs_service)
            doc = service.documents().get(documentId=document_id).execute()
            content = doc.get("body", {}).get("content", [])
            text = self._extract_text_from_content(content)
            return json.dumps(
                {
                    "documentId": doc.get("documentId"),
                    "title": doc.get("title"),
                    "text": text,
                }
            )
        except HttpError as e:
            return json.dumps({"error": f"Google Docs API error: {e}"})
        except Exception as e:
            log_error(f"Could not get document text for {document_id}: {e}")
            return json.dumps({"error": f"Unexpected error: {type(e).__name__}: {e}"})

    async def aget_document_text(self, document_id: str) -> str:
        """Fetch a Google Doc and return only its plain text body (async)."""
        return await asyncio.to_thread(self.get_document_text, document_id=document_id)

    @authenticate
    def batch_update(self, document_id: str, requests: List[Dict[str, Any]]) -> str:
        """
        Apply a batch of update requests to a Google Doc.

        Each request is a Docs API request object: insertText, replaceAllText,
        updateTextStyle, deleteContentRange, insertTable, etc.

        Args:
            document_id (str): The ID of the document to update.
            requests (List[Dict[str, Any]]): Docs API batch request objects.

        Returns:
            str: JSON string with documentId and replies, or error message.
        """
        if not requests:
            return json.dumps({"error": "requests list must not be empty"})
        try:
            service = cast(Resource, self.docs_service)
            result = service.documents().batchUpdate(documentId=document_id, body={"requests": requests}).execute()
            return json.dumps(
                {
                    "documentId": result.get("documentId"),
                    "replies": result.get("replies", []),
                }
            )
        except HttpError as e:
            return json.dumps({"error": f"Google Docs API error: {e}"})
        except Exception as e:
            log_error(f"Could not batch update document {document_id}: {e}")
            return json.dumps({"error": f"Unexpected error: {type(e).__name__}: {e}"})

    async def abatch_update(self, document_id: str, requests: List[Dict[str, Any]]) -> str:
        """Apply a batch of update requests to a Google Doc (async)."""
        return await asyncio.to_thread(self.batch_update, document_id=document_id, requests=requests)

    @authenticate
    def append_text(self, document_id: str, text: str) -> str:
        """
        Append plain text to the end of a Google Doc.

        Fetches the document first to determine the end index, then issues an
        insertText request positioned at the end of the body.

        Args:
            document_id (str): The ID of the document to append to.
            text (str): The text to append (newline characters are preserved).

        Returns:
            str: JSON string with documentId and replies, or error message.
        """
        if not text:
            return json.dumps({"error": "text must not be empty"})
        try:
            service = cast(Resource, self.docs_service)
            doc = service.documents().get(documentId=document_id, fields="body(content(endIndex))").execute()
            content = doc.get("body", {}).get("content", [])
            end_index = 1
            for element in content:
                idx = element.get("endIndex")
                if isinstance(idx, int) and idx > end_index:
                    end_index = idx
            insert_index = max(end_index - 1, 1)
            requests = [{"insertText": {"location": {"index": insert_index}, "text": text}}]
            result = service.documents().batchUpdate(documentId=document_id, body={"requests": requests}).execute()
            return json.dumps(
                {
                    "documentId": result.get("documentId"),
                    "inserted_at_index": insert_index,
                    "replies": result.get("replies", []),
                }
            )
        except HttpError as e:
            return json.dumps({"error": f"Google Docs API error: {e}"})
        except Exception as e:
            log_error(f"Could not append text to document {document_id}: {e}")
            return json.dumps({"error": f"Unexpected error: {type(e).__name__}: {e}"})

    async def aappend_text(self, document_id: str, text: str) -> str:
        """Append plain text to the end of a Google Doc (async)."""
        return await asyncio.to_thread(self.append_text, document_id=document_id, text=text)

    @authenticate
    def export_as_pdf(self, document_id: str, filename: Optional[str] = None) -> str:
        """
        Export a Google Doc as a PDF, saved under the toolkit's export_dir sandbox.

        The original document is unchanged. The caller supplies only a bare
        filename (no directory components, no absolute paths); the toolkit
        resolves it under ``self.export_dir`` to prevent arbitrary filesystem
        writes. Off by default; enable via ``export_as_pdf=True``.

        Args:
            document_id (str): The ID of the document to export.
            filename (Optional[str]): Bare filename for the PDF, e.g.
                ``"plan.pdf"``. Defaults to ``"{document_id}.pdf"``. Path
                separators (``/``, ``\\``) and absolute paths are rejected.

        Returns:
            str: JSON string with path and bytes_written, or error message.
        """
        try:
            safe_name = filename or f"{document_id}.pdf"
            if any(sep in safe_name for sep in ("/", "\\", "\x00")) or Path(safe_name).is_absolute():
                return json.dumps({"error": "filename must be a bare name, not a path"})
            if not safe_name.lower().endswith(".pdf"):
                safe_name += ".pdf"

            target = (self.export_dir / safe_name).resolve()
            if not target.is_relative_to(self.export_dir):
                return json.dumps({"error": "Resolved path escapes export_dir sandbox"})

            drive = cast(Resource, self.drive_service)
            if drive is None:
                return json.dumps({"error": "Drive service is not available"})
            request = drive.files().export_media(fileId=document_id, mimeType="application/pdf")
            buffer = io.BytesIO()
            downloader = MediaIoBaseDownload(buffer, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            data = buffer.getvalue()
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            return json.dumps({"path": str(target), "bytes_written": len(data)})
        except HttpError as e:
            return json.dumps({"error": f"Google Drive API error: {e}"})
        except Exception as e:
            log_error(f"Could not export document {document_id} as PDF: {e}")
            return json.dumps({"error": f"Unexpected error: {type(e).__name__}: {e}"})

    async def aexport_as_pdf(self, document_id: str, filename: Optional[str] = None) -> str:
        """Export a Google Doc as a PDF under export_dir sandbox (async)."""
        return await asyncio.to_thread(self.export_as_pdf, document_id=document_id, filename=filename)

    @authenticate
    def delete_document(self, document_id: str) -> str:
        """
        Move a Google Doc to the Drive trash.

        Uses ``drive.files().update(body={"trashed": True})`` — the document is
        recoverable from the Drive trash for 30 days. This action is destructive
        and is disabled by default; enable via ``delete_document=True``.

        Args:
            document_id (str): The ID of the document to trash.

        Returns:
            str: JSON string with documentId and status, or error message.
        """
        try:
            drive = cast(Resource, self.drive_service)
            if drive is None:
                return json.dumps({"error": "Drive service is not available"})
            drive.files().update(fileId=document_id, body={"trashed": True}).execute()
            return json.dumps({"documentId": document_id, "status": "trashed"})
        except HttpError as e:
            return json.dumps({"error": f"Google Drive API error: {e}"})
        except Exception as e:
            log_error(f"Could not trash document {document_id}: {e}")
            return json.dumps({"error": f"Unexpected error: {type(e).__name__}: {e}"})

    async def adelete_document(self, document_id: str) -> str:
        """Move a Google Doc to the Drive trash (async)."""
        return await asyncio.to_thread(self.delete_document, document_id=document_id)
