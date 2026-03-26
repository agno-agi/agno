"""
Google Slides Toolset for interacting with Slides API

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
3. Enable the Google Slides API and Google Drive API:
   - Go to "APIs & Services" > "Enable APIs and Services"
   - Search for "Google Slides API" and "Google Drive API"
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
   export GOOGLE_REDIRECT_URI=http://localhost  # Default value
   ```

Alternatively, for Server-to-Server use cases you can use a Service Account:
   export GOOGLE_SERVICE_ACCOUNT_FILE=path/to/service-account.json
"""

import json
import textwrap
import uuid
from os import getenv
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlparse

try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google.oauth2.service_account import Credentials as ServiceAccountCredentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
except ImportError:
    raise ImportError(
        "`google-api-python-client` `google-auth-httplib2` `google-auth-oauthlib` not installed. "
        "Please install using `pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib`"
    )

from agno.tools import Toolkit
from agno.tools.google.auth import google_authenticate
from agno.utils.log import log_debug

SLIDES_INSTRUCTIONS = textwrap.dedent("""\
    You have access to Google Slides tools for creating and managing presentations.

    ## Key Workflow
    - Call create_presentation to start a new deck, or list_presentations to find existing ones
    - Always call get_presentation_metadata before modifying slides to get current slide IDs
    - Never guess slide IDs or object IDs — use the values returned by the API

    ## Tips
    - Use add_slide with layouts: TITLE, TITLE_AND_BODY, TITLE_AND_TWO_COLUMNS, SECTION_HEADER, BLANK
    - Use add_text_box for custom positioned text, add_table for structured data
    - Use get_slide_text or read_all_text to extract content from presentations
    - Destructive tools (delete_presentation, delete_slide) are disabled by default""")


authenticate = google_authenticate("slides")


class GoogleSlidesTools(Toolkit):
    DEFAULT_SCOPES = [
        "https://www.googleapis.com/auth/presentations",
        "https://www.googleapis.com/auth/drive.file",
    ]

    def __init__(
        self,
        scopes: Optional[List[str]] = None,
        creds: Optional[Union[Credentials, ServiceAccountCredentials]] = None,
        credentials_path: Optional[str] = None,
        token_path: Optional[str] = None,
        service_account_path: Optional[str] = None,
        delegated_user: Optional[str] = None,
        oauth_port: int = 0,
        login_hint: Optional[str] = None,
        create_presentation: bool = True,
        get_presentation: bool = True,
        list_presentations: bool = True,
        get_presentation_metadata: bool = True,
        get_page: bool = True,
        get_slide_text: bool = True,
        read_all_text: bool = True,
        get_slide_thumbnail: bool = True,
        add_slide: bool = True,
        add_text_box: bool = True,
        add_table: bool = True,
        set_background_image: bool = True,
        duplicate_slide: bool = True,
        move_slides: bool = True,
        insert_youtube_video: bool = True,
        insert_drive_video: bool = True,
        delete_presentation: bool = False,
        delete_slide: bool = False,
        all: bool = False,
        instructions: Optional[str] = None,
        add_instructions: bool = True,
        **kwargs,
    ):
        self.creds = creds
        self.credentials_path = credentials_path
        self.token_path = token_path
        self.service_account_path = service_account_path
        self.delegated_user = delegated_user
        self.oauth_port = oauth_port
        self.login_hint = login_hint
        self.scopes = scopes or self.DEFAULT_SCOPES

        self.service: Any = None
        self.slides_service: Any = None
        self.drive_service: Any = None

        tools = []
        if all or create_presentation:
            tools.append(self.create_presentation)
        if all or get_presentation:
            tools.append(self.get_presentation)
        if all or list_presentations:
            tools.append(self.list_presentations)
        if all or get_presentation_metadata:
            tools.append(self.get_presentation_metadata)
        if all or get_page:
            tools.append(self.get_page)
        if all or get_slide_text:
            tools.append(self.get_slide_text)
        if all or read_all_text:
            tools.append(self.read_all_text)
        if all or get_slide_thumbnail:
            tools.append(self.get_slide_thumbnail)
        if all or add_slide:
            tools.append(self.add_slide)
        if all or add_text_box:
            tools.append(self.add_text_box)
        if all or add_table:
            tools.append(self.add_table)
        if all or set_background_image:
            tools.append(self.set_background_image)
        if all or duplicate_slide:
            tools.append(self.duplicate_slide)
        if all or move_slides:
            tools.append(self.move_slides)
        if all or insert_youtube_video:
            tools.append(self.insert_youtube_video)
        if all or insert_drive_video:
            tools.append(self.insert_drive_video)
        if all or delete_presentation:
            tools.append(self.delete_presentation)
        if all or delete_slide:
            tools.append(self.delete_slide)

        if instructions is None:
            self.instructions = SLIDES_INSTRUCTIONS
        else:
            self.instructions = instructions

        super().__init__(
            name="google_slides_tools",
            tools=tools,
            add_instructions=add_instructions,
            **kwargs,
        )

    def _build_service(self):
        self.slides_service = build("slides", "v1", credentials=self.creds)
        self.drive_service = build("drive", "v3", credentials=self.creds)
        # Returned value stored as self.service by decorator (sentinel for "services built")
        return self.slides_service

    def _auth(self) -> None:
        """Authenticate with Google Slides API"""
        if self.creds and self.creds.valid:
            return

        service_account_path = self.service_account_path or getenv("GOOGLE_SERVICE_ACCOUNT_FILE")
        if service_account_path:
            sa_creds = ServiceAccountCredentials.from_service_account_file(service_account_path, scopes=self.scopes)
            delegated_user = self.delegated_user or getenv("GOOGLE_DELEGATED_USER")
            if delegated_user:
                sa_creds = sa_creds.with_subject(delegated_user)
            # Eagerly fetch token so creds.valid=True and @authenticate won't re-enter _auth
            sa_creds.refresh(Request())
            self.creds = sa_creds
            return

        token_file = Path(self.token_path or "token.json")
        creds_file = Path(self.credentials_path or "credentials.json")

        if token_file.exists():
            try:
                self.creds = Credentials.from_authorized_user_file(str(token_file), self.scopes)
            except ValueError:
                # Token file missing refresh_token — fall through to re-auth
                self.creds = None

        if self.creds and self.creds.expired and self.creds.refresh_token:  # type: ignore
            try:
                self.creds.refresh(Request())
            except Exception:
                # Refresh token revoked or expired — fall through to re-auth
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

            # prompt=consent forces Google to return a refresh_token every time
            oauth_kwargs: Dict[str, Any] = {"prompt": "consent"}
            if self.login_hint:
                oauth_kwargs["login_hint"] = self.login_hint
            oauth_kwargs["port"] = self.oauth_port
            self.creds = flow.run_local_server(**oauth_kwargs)
        # Save the credentials for future use
        if self.creds and self.creds.valid:
            token_file.write_text(self.creds.to_json())  # type: ignore[union-attr]
            log_debug("Google Slides credentials saved")

    def _batch_update(self, presentation_id: str, requests: List[Dict[str, Any]]) -> dict:
        return (
            self.slides_service.presentations()
            .batchUpdate(presentationId=presentation_id, body={"requests": requests})
            .execute()
        )

    def _generate_id(self, prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex[:12]}"

    def _to_emu(self, value: Union[int, float], unit: str = "inch") -> int:
        if unit == "inch":
            return int(value * 914400)
        if unit == "point":
            return int(value * 12700)
        return int(value)

    def _extract_text(self, text_elements: List[Dict]) -> List[str]:
        result = []
        for te in text_elements:
            content = ""
            if "textRun" in te:
                content = te["textRun"].get("content", "")
            elif "autoText" in te:
                content = te["autoText"].get("content", "")
            if content.strip():
                result.append(content.strip())
        return result

    def _extract_text_recursive(self, element: Dict[str, Any]) -> List[str]:
        if "shape" in element:
            return self._extract_text(element["shape"].get("text", {}).get("textElements", []))
        elif "table" in element:
            lines = []
            for row in element["table"].get("tableRows", []):
                for cell in row.get("tableCells", []):
                    lines.extend(self._extract_text(cell.get("text", {}).get("textElements", [])))
            return lines
        elif "elementGroup" in element:
            lines = []
            for child in element["elementGroup"].get("children", []):
                lines.extend(self._extract_text_recursive(child))
            return lines
        elif "wordArt" in element:
            content = element.get("wordArt", {}).get("renderedText", "").strip()
            return [content] if content else []
        return []

    def _insert_video(
        self,
        presentation_id: str,
        slide_id: str,
        video_id: str,
        source: str,
        x: Union[int, float] = 0,
        y: Union[int, float] = 0,
        width: Union[int, float] = 5486400,
        height: Union[int, float] = 3086100,
        id_alias: str = "video",
    ) -> str:
        obj_id = self._generate_id(id_alias)
        requests: List[Dict[str, Any]] = [
            {
                "createVideo": {
                    "objectId": obj_id,
                    "source": source,
                    "id": video_id,
                    "elementProperties": {
                        "pageObjectId": slide_id,
                        "size": {
                            "width": {"magnitude": width, "unit": "EMU"},
                            "height": {"magnitude": height, "unit": "EMU"},
                        },
                        "transform": {
                            "scaleX": 1,
                            "scaleY": 1,
                            "translateX": x,
                            "translateY": y,
                            "unit": "EMU",
                        },
                    },
                }
            }
        ]
        self._batch_update(presentation_id, requests)
        return obj_id

    @authenticate
    def create_presentation(self, title: str) -> str:
        """
        Creates a blank Google Slides presentation.

        Args:
            title (str): Title of the new presentation.

        Returns:
            str: JSON with presentation_id, url, and title.
        """
        try:
            if not title.strip():
                return json.dumps({"error": "title cannot be empty."})
            result = self.slides_service.presentations().create(body={"title": title}).execute()
            pres_id = result["presentationId"]
            return json.dumps(
                {
                    "presentation_id": pres_id,
                    "url": f"https://docs.google.com/presentation/d/{pres_id}",
                    "title": title,
                }
            )
        except Exception as e:
            return json.dumps({"error": str(e)})

    @authenticate
    def get_presentation(self, presentation_id: str, fields: Optional[str] = None) -> str:
        """
        Fetches a presentation's full metadata and content by ID.

        Args:
            presentation_id (str): The presentation ID.
            fields (str, optional): Comma-separated fields to return e.g. "slides,title".

        Returns:
            str: JSON representation of the presentation object.
        """
        try:
            if not presentation_id.strip():
                return json.dumps({"error": "presentation_id cannot be empty."})

            result = self.slides_service.presentations().get(presentationId=presentation_id, fields=fields).execute()
            return json.dumps(result)
        except Exception as e:
            return json.dumps({"error": str(e)})

    @authenticate
    def list_presentations(self, page_size: int = 20, page_token: Optional[str] = None) -> str:
        """
        Lists all Google Slides presentations accessible to the authenticated account.

        Args:
            page_size (int): Maximum results to return. Defaults to 20.
            page_token (str, optional): Token for the next page of results.

        Returns:
            str: JSON with presentations list and next_page_token.
        """
        try:
            if page_size <= 0:
                return json.dumps({"error": "page_size must be a positive integer."})
            response = (
                self.drive_service.files()
                .list(
                    q="mimeType='application/vnd.google-apps.presentation'",
                    pageSize=page_size,
                    pageToken=page_token,
                    fields="nextPageToken, files(id, name, createdTime, modifiedTime)",
                )
                .execute()
            )
            files = response.get("files", [])
            next_token = response.get("nextPageToken")
            return json.dumps({"presentations": files, "next_page_token": next_token})
        except Exception as e:
            return json.dumps({"error": str(e)})

    @authenticate
    def delete_presentation(self, presentation_id: str) -> str:
        """
        Permanently deletes a presentation via the Google Drive API.

        Args:
            presentation_id (str): The presentation ID to delete.

        Returns:
            str: JSON confirmation with deleted presentation ID.
        """
        try:
            if not presentation_id.strip():
                return json.dumps({"error": "presentation_id cannot be empty."})

            self.drive_service.files().delete(fileId=presentation_id).execute()
            return json.dumps({"deleted": presentation_id})
        except Exception as e:
            return json.dumps({"error": str(e)})

    @authenticate
    def add_slide(
        self,
        presentation_id: str,
        layout: str = "TITLE_AND_BODY",
        title: Optional[str] = None,
        subtitle: Optional[str] = None,
        body: Optional[str] = None,
        body_2: Optional[str] = None,
        insertion_index: Optional[int] = None,
    ) -> str:
        """
        Adds a new slide with a layout and optional title/subtitle/body text.

        Args:
            presentation_id (str): The presentation ID.
            layout (str): Slide layout, e.g. TITLE, TITLE_AND_BODY, BLANK, SECTION_HEADER.
            title (str, optional): Title placeholder text.
            subtitle (str, optional): Subtitle placeholder text.
            body (str, optional): Body placeholder text.
            body_2 (str, optional): Second column body text (for TITLE_AND_TWO_COLUMNS).
            insertion_index (int, optional): 0-based position. Appends if omitted.

        Returns:
            str: JSON with slide_id, layout, and warnings.
        """
        try:
            if not presentation_id.strip():
                return json.dumps({"error": "presentation_id cannot be empty."})

            if insertion_index is not None and insertion_index < 0:
                return json.dumps({"error": "insertion_index must be >= 0."})

            valid_layouts = {
                "BLANK",
                "TITLE",
                "TITLE_AND_BODY",
                "TITLE_ONLY",
                "SECTION_HEADER",
                "SECTION_TITLE_AND_DESCRIPTION",
                "ONE_COLUMN_TEXT",
                "MAIN_POINT",
                "BIG_NUMBER",
                "CAPTION_ONLY",
                "TITLE_AND_TWO_COLUMNS",
            }
            if layout not in valid_layouts:
                return json.dumps(
                    {"error": f"Invalid layout '{layout}'. Must be one of: {', '.join(sorted(valid_layouts))}"}
                )

            slide_id = self._generate_id("slide")

            create_req: dict = {
                "createSlide": {
                    "objectId": slide_id,
                    "slideLayoutReference": {"predefinedLayout": layout},
                }
            }
            if insertion_index is not None:
                create_req["createSlide"]["insertionIndex"] = insertion_index

            self._batch_update(presentation_id, [create_req])

            insert_errors: List[str] = []
            if any((title, subtitle, body, body_2)):
                try:
                    page_data = (
                        self.slides_service.presentations()
                        .pages()
                        .get(
                            presentationId=presentation_id,
                            pageObjectId=slide_id,
                            fields="pageElements(objectId,shape(placeholder))",
                        )
                        .execute()
                    )
                    temp_title, temp_subtitle, temp_body, temp_body_2 = title, subtitle, body, body_2
                    text_reqs = []
                    body_count = 0
                    for el in page_data.get("pageElements", []):
                        shape = el.get("shape", {})
                        ph = shape.get("placeholder", {})
                        ph_type = ph.get("type")
                        obj_id = el.get("objectId")

                        if temp_title and ph_type in ["TITLE", "CENTERED_TITLE"]:
                            text_reqs.append(
                                {"insertText": {"objectId": obj_id, "text": temp_title, "insertionIndex": 0}}
                            )
                            temp_title = None  # consumed
                        elif temp_subtitle and ph_type in ["SUBTITLE"]:
                            text_reqs.append(
                                {"insertText": {"objectId": obj_id, "text": temp_subtitle, "insertionIndex": 0}}
                            )
                            temp_subtitle = None
                        elif ph_type in ["BODY"]:
                            if body_count == 0 and temp_body:
                                text_reqs.append(
                                    {"insertText": {"objectId": obj_id, "text": temp_body, "insertionIndex": 0}}
                                )
                                temp_body = None
                                body_count += 1
                            elif body_count == 1 and temp_body_2:
                                text_reqs.append(
                                    {"insertText": {"objectId": obj_id, "text": temp_body_2, "insertionIndex": 0}}
                                )
                                temp_body_2 = None
                                body_count += 1

                    if text_reqs:
                        self._batch_update(presentation_id, text_reqs)
                        title, subtitle, body, body_2 = temp_title, temp_subtitle, temp_body, temp_body_2
                except Exception as ph_err:
                    insert_errors.append(str(ph_err))

            return json.dumps(
                {
                    "slide_id": slide_id,
                    "layout": layout,
                    "title": title,
                    "subtitle": subtitle,
                    "body": body,
                    "body_2": body_2,
                    "warnings": insert_errors if insert_errors else None,
                }
            )
        except Exception as e:
            return json.dumps({"error": str(e)})

    @authenticate
    def delete_slide(self, presentation_id: str, slide_id: str) -> str:
        """
        Removes a slide from the presentation.

        Args:
            presentation_id (str): The presentation ID.
            slide_id (str): Object ID of the slide.

        Returns:
            str: JSON confirmation with deleted slide ID.
        """
        try:
            if not presentation_id.strip():
                return json.dumps({"error": "presentation_id cannot be empty."})
            if not slide_id.strip():
                return json.dumps({"error": "object_id cannot be empty."})

            self._batch_update(presentation_id, [{"deleteObject": {"objectId": slide_id}}])
            return json.dumps({"deleted_slide": slide_id})
        except Exception as e:
            return json.dumps({"error": str(e)})

    @authenticate
    def duplicate_slide(self, presentation_id: str, slide_id: str) -> str:
        """
        Duplicates a slide, inserting the copy after the original.

        Args:
            presentation_id (str): The presentation ID.
            slide_id (str): Object ID of the slide to duplicate.

        Returns:
            str: JSON batchUpdate response.
        """
        try:
            if not presentation_id.strip():
                return json.dumps({"error": "presentation_id cannot be empty."})
            if not slide_id.strip():
                return json.dumps({"error": "object_id cannot be empty."})

            result = self._batch_update(presentation_id, [{"duplicateObject": {"objectId": slide_id}}])
            return json.dumps(result)
        except Exception as e:
            return json.dumps({"error": str(e)})

    @authenticate
    def move_slides(
        self,
        presentation_id: str,
        slide_ids: List[str],
        insertion_index: int,
    ) -> str:
        """
        Reorders slides to a target position.

        Args:
            presentation_id (str): The presentation ID.
            slide_ids (list[str]): Ordered slide object IDs to move.
            insertion_index (int): Target 0-based position.

        Returns:
            str: JSON confirmation with moved IDs and target index.
        """
        try:
            if not presentation_id.strip():
                return json.dumps({"error": "presentation_id cannot be empty."})

            if not slide_ids:
                return json.dumps({"error": "slide_ids list cannot be empty."})
            if insertion_index < 0:
                return json.dumps({"error": "insertion_index must be >= 0."})

            self._batch_update(
                presentation_id,
                [
                    {
                        "updateSlidesPosition": {
                            "slideObjectIds": slide_ids,
                            "insertionIndex": insertion_index,
                        }
                    }
                ],
            )
            return json.dumps({"moved": slide_ids, "to_index": insertion_index})
        except Exception as e:
            return json.dumps({"error": str(e)})

    @authenticate
    def add_text_box(
        self,
        presentation_id: str,
        slide_id: str,
        text: str,
        x: Union[int, float] = 1.0,
        y: Union[int, float] = 1.0,
        width: Union[int, float] = 8.0,
        height: Union[int, float] = 1.0,
    ) -> str:
        """
        Creates a positioned text box on a slide.

        Args:
            presentation_id (str): The presentation ID.
            slide_id (str): The slide object ID.
            text (str): Text content.
            x (int/float): X position in inches. Default 1.0.
            y (int/float): Y position in inches. Default 1.0.
            width (int/float): Width in inches. Default 8.0.
            height (int/float): Height in inches. Default 1.0.

        Returns:
            str: JSON with text_box_id and slide_id.
        """
        try:
            if not presentation_id.strip():
                return json.dumps({"error": "presentation_id cannot be empty."})
            if not slide_id.strip():
                return json.dumps({"error": "object_id cannot be empty."})

            if not text or not text.strip():
                return json.dumps({"error": "text cannot be empty."})
            if width <= 0 or height <= 0:
                return json.dumps({"error": "Width and height must be positive."})

            box_id = self._generate_id("textbox")
            emu_x, emu_y = self._to_emu(x), self._to_emu(y)
            emu_width, emu_height = self._to_emu(width), self._to_emu(height)

            requests: List[Dict[str, Any]] = [
                {
                    "createShape": {
                        "objectId": box_id,
                        "shapeType": "TEXT_BOX",
                        "elementProperties": {
                            "pageObjectId": slide_id,
                            "size": {
                                "width": {"magnitude": emu_width, "unit": "EMU"},
                                "height": {"magnitude": emu_height, "unit": "EMU"},
                            },
                            "transform": {
                                "scaleX": 1,
                                "scaleY": 1,
                                "translateX": emu_x,
                                "translateY": emu_y,
                                "unit": "EMU",
                            },
                        },
                    }
                },
                {"insertText": {"objectId": box_id, "text": text, "insertionIndex": 0}},
            ]
            self._batch_update(presentation_id, requests)
            return json.dumps({"text_box_id": box_id, "slide_id": slide_id})
        except Exception as e:
            return json.dumps({"error": str(e)})

    @authenticate
    def add_table(
        self,
        presentation_id: str,
        slide_id: str,
        rows: int,
        columns: int,
        content: Optional[list[list[str]]] = None,
    ) -> str:
        """
        Creates a table on a slide, optionally pre-populated with content.

        Args:
            presentation_id (str): The presentation ID.
            slide_id (str): The slide object ID.
            rows (int): Number of rows.
            columns (int): Number of columns.
            content (list[list[str]], optional): 2D list of cell values.

        Returns:
            str: JSON with table_id, rows, and columns.
        """
        try:
            if not presentation_id.strip():
                return json.dumps({"error": "presentation_id cannot be empty."})
            if not slide_id.strip():
                return json.dumps({"error": "object_id cannot be empty."})

            if rows <= 0 or columns <= 0:
                return json.dumps({"error": "Rows and columns must be positive integers."})

            if content and (len(content) > rows or any(len(r) > columns for r in content)):
                return json.dumps({"error": "Content dimensions exceed table dimensions."})

            table_id = self._generate_id("table")
            requests: List[Dict[str, Any]] = [
                {
                    "createTable": {
                        "objectId": table_id,
                        "elementProperties": {"pageObjectId": slide_id},
                        "rows": rows,
                        "columns": columns,
                    }
                }
            ]
            if content:
                for r_idx, row in enumerate(content):
                    for c_idx, cell in enumerate(row):
                        if cell:
                            requests.append(
                                {
                                    "insertText": {
                                        "objectId": table_id,
                                        "cellLocation": {"rowIndex": r_idx, "columnIndex": c_idx},
                                        "text": cell,
                                        "insertionIndex": 0,
                                    }
                                }
                            )
            self._batch_update(presentation_id, requests)
            return json.dumps({"table_id": table_id, "rows": rows, "columns": columns})
        except Exception as e:
            return json.dumps({"error": str(e)})

    @authenticate
    def set_background_image(
        self,
        presentation_id: str,
        slide_id: str,
        image_url: str,
    ) -> str:
        """
        Sets a publicly accessible image as the background of a slide.

        Args:
            presentation_id (str): The presentation ID.
            slide_id (str): The slide object ID.
            image_url (str): Publicly accessible image URL.

        Returns:
            str: JSON confirmation with slide_id.
        """
        try:
            if not presentation_id.strip():
                return json.dumps({"error": "presentation_id cannot be empty."})
            if not slide_id.strip():
                return json.dumps({"error": "object_id cannot be empty."})

            if not image_url or not image_url.strip():
                return json.dumps({"error": "image_url cannot be empty."})

            parsed = urlparse(image_url)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                return json.dumps({"error": "image_url must be a valid http or https URL."})

            self._batch_update(
                presentation_id,
                [
                    {
                        "updatePageProperties": {
                            "objectId": slide_id,
                            "pageProperties": {
                                "pageBackgroundFill": {"stretchedPictureFill": {"contentUrl": image_url}}
                            },
                            "fields": "pageBackgroundFill",
                        }
                    }
                ],
            )
            return json.dumps({"background_set": True, "slide_id": slide_id})
        except Exception as e:
            return json.dumps({"error": str(e)})

    @authenticate
    def read_all_text(self, presentation_id: str) -> str:
        """
        Extracts all text from every slide in the presentation.

        Args:
            presentation_id (str): The presentation ID.

        Returns:
            str: JSON mapping slide IDs to lists of text strings.
        """
        try:
            if not presentation_id.strip():
                return json.dumps({"error": "presentation_id cannot be empty."})

            fields = (
                "slides(objectId,pageElements("
                "shape(text),"
                "table(tableRows(tableCells(text))),"
                "elementGroup(children(shape(text),table(tableRows(tableCells(text))),wordArt)),"
                "wordArt"
                "))"
            )
            pres = self.slides_service.presentations().get(presentationId=presentation_id, fields=fields).execute()
            result: Dict[str, List[str]] = {}
            for slide in pres.get("slides", []):
                sid = slide["objectId"]
                lines = []
                for el in slide.get("pageElements", []):
                    lines.extend(self._extract_text_recursive(el))
                result[sid] = lines
            return json.dumps(result)
        except Exception as e:
            return json.dumps({"error": str(e)})

    @authenticate
    def get_slide_thumbnail(self, presentation_id: str, slide_id: str) -> str:
        """
        Returns the thumbnail image URL for a specific slide.

        Args:
            presentation_id (str): The presentation ID.
            slide_id (str): The slide object ID.

        Returns:
            str: JSON with thumbnail_url.
        """
        try:
            if not presentation_id.strip():
                return json.dumps({"error": "presentation_id cannot be empty."})
            if not slide_id.strip():
                return json.dumps({"error": "object_id cannot be empty."})

            response = (
                self.slides_service.presentations()
                .pages()
                .getThumbnail(presentationId=presentation_id, pageObjectId=slide_id)
                .execute()
            )
            url = response.get("contentUrl")
            if not url:
                return json.dumps({"error": f"No thumbnail URL found for slide {slide_id}"})
            return json.dumps({"thumbnail_url": url})
        except Exception as e:
            return json.dumps({"error": str(e)})

    @authenticate
    def get_presentation_metadata(self, presentation_id: str) -> str:
        """
        Fetches lightweight metadata about a presentation.

        Args:
            presentation_id (str): The presentation ID.

        Returns:
            str: JSON with title, slide_count, slides, and page dimensions.
        """
        try:
            if not presentation_id.strip():
                return json.dumps({"error": "presentation_id cannot be empty."})

            result = (
                self.slides_service.presentations()
                .get(
                    presentationId=presentation_id,
                    fields=(
                        "presentationId,title,pageSize,"
                        "slides(objectId,slideProperties(layoutObjectId),"
                        "pageElements(objectId,size,transform,shape(shapeType,placeholder(type))))"
                    ),
                )
                .execute()
            )
            page_size = result.get("pageSize", {})
            width_emu = page_size.get("width", {}).get("magnitude", 9144000)
            height_emu = page_size.get("height", {}).get("magnitude", 5143500)

            slides_info = []
            for slide in result.get("slides", []):
                elements = []
                for el in slide.get("pageElements", []):
                    el_info: Dict[str, Any] = {"object_id": el.get("objectId")}
                    shape = el.get("shape", {})
                    if shape.get("shapeType"):
                        el_info["type"] = shape["shapeType"]
                    ph = shape.get("placeholder", {})
                    if ph.get("type"):
                        el_info["placeholder"] = ph["type"]
                    transform = el.get("transform", {})
                    if transform:
                        el_info["x_inches"] = round(transform.get("translateX", 0) / 914400, 2)
                        el_info["y_inches"] = round(transform.get("translateY", 0) / 914400, 2)
                    size = el.get("size", {})
                    if size:
                        el_info["width_inches"] = round(size.get("width", {}).get("magnitude", 0) / 914400, 2)
                        el_info["height_inches"] = round(size.get("height", {}).get("magnitude", 0) / 914400, 2)
                    elements.append(el_info)
                slides_info.append(
                    {
                        "slide_id": slide["objectId"],
                        "layout": slide.get("slideProperties", {}).get("layoutObjectId"),
                        "elements": elements,
                    }
                )

            return json.dumps(
                {
                    "presentation_id": result.get("presentationId"),
                    "title": result.get("title"),
                    "slide_count": len(slides_info),
                    "page_width_inches": round(width_emu / 914400, 2),
                    "page_height_inches": round(height_emu / 914400, 2),
                    "slides": slides_info,
                }
            )
        except Exception as e:
            return json.dumps({"error": str(e)})

    @authenticate
    def get_page(self, presentation_id: str, page_object_id: str) -> str:
        """
        Retrieves the full content of a specific slide by its object ID.

        Args:
            presentation_id (str): The presentation ID.
            page_object_id (str): The object ID of the slide.

        Returns:
            str: JSON representation of the page object.
        """
        try:
            if not presentation_id.strip():
                return json.dumps({"error": "presentation_id cannot be empty."})
            if not page_object_id.strip():
                return json.dumps({"error": "object_id cannot be empty."})

            result = (
                self.slides_service.presentations()
                .pages()
                .get(presentationId=presentation_id, pageObjectId=page_object_id)
                .execute()
            )
            return json.dumps(result)
        except Exception as e:
            return json.dumps({"error": str(e)})

    @authenticate
    def get_slide_text(self, presentation_id: str, page_object_id: str) -> str:
        """
        Extracts the text content from a single slide.

        Args:
            presentation_id (str): The presentation ID.
            page_object_id (str): The object ID of the slide.

        Returns:
            str: JSON with slide_id and text list.
        """
        try:
            if not presentation_id.strip():
                return json.dumps({"error": "presentation_id cannot be empty."})
            if not page_object_id.strip():
                return json.dumps({"error": "object_id cannot be empty."})

            page = (
                self.slides_service.presentations()
                .pages()
                .get(presentationId=presentation_id, pageObjectId=page_object_id)
                .execute()
            )
            lines = []
            for el in page.get("pageElements", []):
                lines.extend(self._extract_text_recursive(el))
            return json.dumps({"slide_id": page_object_id, "text": lines})
        except Exception as e:
            return json.dumps({"error": str(e)})

    @authenticate
    def insert_youtube_video(
        self,
        presentation_id: str,
        slide_id: str,
        video_id: str,
        x: Union[int, float] = 1.6,
        y: Union[int, float] = 1.6,
        width: Union[int, float] = 5.0,
        height: Union[int, float] = 3.0,
    ) -> str:
        """
        Embeds a YouTube video on a slide.

        Args:
            presentation_id (str): The presentation ID.
            slide_id (str): The slide object ID.
            video_id (str): YouTube video ID (the value after 'v=' in the URL).
            x (int/float): X position in inches. Default 1.6.
            y (int/float): Y position in inches. Default 1.6.
            width (int/float): Width in inches. Default 5.0.
            height (int/float): Height in inches. Default 3.0.

        Returns:
            str: JSON with video_object_id and slide_id.
        """
        try:
            if not presentation_id.strip():
                return json.dumps({"error": "presentation_id cannot be empty."})
            if not slide_id.strip():
                return json.dumps({"error": "object_id cannot be empty."})

            if not video_id or not video_id.strip():
                return json.dumps({"error": "video_id cannot be empty."})
            if width <= 0 or height <= 0:
                return json.dumps({"error": "Width and height must be positive."})

            emu_x, emu_y = self._to_emu(x), self._to_emu(y)
            emu_width, emu_height = self._to_emu(width), self._to_emu(height)

            video_obj_id = self._insert_video(
                presentation_id=presentation_id,
                slide_id=slide_id,
                video_id=video_id,
                source="YOUTUBE",
                x=emu_x,
                y=emu_y,
                width=emu_width,
                height=emu_height,
                id_alias="video_yt",
            )
            return json.dumps({"video_object_id": video_obj_id, "slide_id": slide_id, "youtube_video_id": video_id})
        except Exception as e:
            return json.dumps({"error": str(e)})

    @authenticate
    def insert_drive_video(
        self,
        presentation_id: str,
        slide_id: str,
        file_id: str,
        x: Union[int, float] = 1.6,
        y: Union[int, float] = 1.6,
        width: Union[int, float] = 5.0,
        height: Union[int, float] = 3.0,
    ) -> str:
        """
        Embeds a Google Drive video on a slide.

        Args:
            presentation_id (str): The presentation ID.
            slide_id (str): The slide object ID.
            file_id (str): The Google Drive file ID.
            x (int/float): X position in inches. Default 1.6.
            y (int/float): Y position in inches. Default 1.6.
            width (int/float): Width in inches. Default 5.0.
            height (int/float): Height in inches. Default 3.0.

        Returns:
            str: JSON with video_object_id and slide_id.
        """
        try:
            if not presentation_id.strip():
                return json.dumps({"error": "presentation_id cannot be empty."})
            if not slide_id.strip():
                return json.dumps({"error": "object_id cannot be empty."})

            if not file_id or not file_id.strip():
                return json.dumps({"error": "file_id cannot be empty."})
            if width <= 0 or height <= 0:
                return json.dumps({"error": "Width and height must be positive."})

            emu_x, emu_y = self._to_emu(x), self._to_emu(y)
            emu_width, emu_height = self._to_emu(width), self._to_emu(height)

            video_obj_id = self._insert_video(
                presentation_id=presentation_id,
                slide_id=slide_id,
                video_id=file_id,
                source="DRIVE",
                x=emu_x,
                y=emu_y,
                width=emu_width,
                height=emu_height,
                id_alias="video_drive",
            )
            return json.dumps({"video_object_id": video_obj_id, "slide_id": slide_id, "drive_file_id": file_id})
        except Exception as e:
            return json.dumps({"error": str(e)})
