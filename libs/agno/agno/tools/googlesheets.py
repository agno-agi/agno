"""
Google Sheets Toolset for interacting with Sheets API

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
3. Enable the Google Sheets API:
   - Go to "APIs & Services" > "Enable APIs and Services"
   - Search for "Google Sheets API"
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

5. Set up environment variables:
   Create a .envrc file in your project root with:
   ```
   export GOOGLE_CLIENT_ID=your_client_id_here
   export GOOGLE_CLIENT_SECRET=your_client_secret_here
   export GOOGLE_PROJECT_ID=your_project_id_here
   export GOOGLE_REDIRECT_URI=http://localhost  # Default value
   ```

Alternatively, follow the instructions in the Google Sheets API Quickstart guide:
1: Steps: https://developers.google.com/sheets/api/quickstart/python
2: Save the credentials.json file to the root of the project or update the path in the GoogleSheetsTools class

Note: The first time you run the application, it will open a browser window for OAuth authentication.
A token.json file will be created to store the authentication credentials for future use.
"""

import json
from functools import wraps
from os import getenv
from pathlib import Path
from typing import Any, List, Optional

from agno.tools import Toolkit

try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import Resource, build
except ImportError:
    raise ImportError(
        "`google-api-python-client` `google-auth-httplib2` `google-auth-oauthlib` not installed. Please install using `pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib`"
    )


def authenticate(func):
    """Decorator to ensure authentication before executing a function."""

    @wraps(func)
    def wrapper(self, *args, **kwargs):
        if not self.creds or not self.creds.valid:
            self._auth()
        if not self.service:
            self.service = build("sheets", "v4", credentials=self.creds)
        return func(self, *args, **kwargs)

    return wrapper


class GoogleSheetsTools(Toolkit):
    # Default scopes for Google Sheets API access
    DEFAULT_SCOPES = {
        "read": "https://www.googleapis.com/auth/spreadsheets.readonly",
        "write": "https://www.googleapis.com/auth/spreadsheets",
    }

    service: Optional[Resource]

    def __init__(
        self,
        scopes: Optional[List[str]] = None,
        spreadsheet_id: Optional[str] = None,
        spreadsheet_range: Optional[str] = None,
        creds: Optional[Credentials] = None,
        creds_path: Optional[str] = None,
        token_path: Optional[str] = None,
        read: bool = True,
        create: bool = False,
        update: bool = False,
        duplicate: bool = False,
    ):
        """Initialize GoogleSheetsTools with the specified configuration.

        Args:
            scopes (Optional[List[str]]): Custom OAuth scopes. If None, determined by operations.
            spreadsheet_id (Optional[str]): ID of the target spreadsheet.
            spreadsheet_range (Optional[str]): Range within the spreadsheet.
            creds (Optional[Credentials]): Pre-existing credentials.
            creds_path (Optional[str]): Path to credentials file.
            token_path (Optional[str]): Path to token file.
            read (bool): Enable read operations. Defaults to True.
            create (bool): Enable create operations. Defaults to False.
            update (bool): Enable update operations. Defaults to False.
            duplicate (bool): Enable duplicate operations. Defaults to False.
        """
        super().__init__(name="google_tools")
        self.spreadsheet_id = spreadsheet_id
        self.spreadsheet_range = spreadsheet_range
        self.creds = creds
        self.credentials_path = creds_path
        self.token_path = token_path
        self.service: Optional[Resource] = None

        # Determine required scopes based on operations if no custom scopes provided
        if scopes is None:
            self.scopes = []
            if read:
                self.scopes.append(self.DEFAULT_SCOPES["read"])
            if create or update or duplicate:
                self.scopes.append(self.DEFAULT_SCOPES["write"])
            # Remove duplicates while preserving order
            self.scopes = list(dict.fromkeys(self.scopes))
        else:
            self.scopes = scopes
            # Validate that required scopes are present for requested operations
            if (create or update or duplicate) and self.DEFAULT_SCOPES["write"] not in self.scopes:
                raise ValueError(f"The scope {self.DEFAULT_SCOPES['write']} is required for write operations")
            if (
                read
                and self.DEFAULT_SCOPES["read"] not in self.scopes
                and self.DEFAULT_SCOPES["write"] not in self.scopes
            ):
                raise ValueError(
                    f"Either {self.DEFAULT_SCOPES['read']} or {self.DEFAULT_SCOPES['write']} is required for read operations"
                )

        if read:
            self.register(self.read_sheet)
        if create:
            self.register(self.create_sheet)
        if update:
            self.register(self.update_sheet)
        if duplicate:
            self.register(self.create_duplicate_sheet)

    def _auth(self) -> None:
        """
        Authenticate with Google Sheets API
        """
        if self.creds and self.creds.valid:
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
                if creds_file.exists():
                    flow = InstalledAppFlow.from_client_secrets_file(str(creds_file), self.scopes)
                else:
                    flow = InstalledAppFlow.from_client_config(client_config, self.scopes)
                self.creds = flow.run_local_server(port=0)
            token_file.write_text(self.creds.to_json()) if self.creds else None

    @authenticate
    def read_sheet(self, spreadsheet_id: Optional[str] = None, spreadsheet_range: Optional[str] = None) -> str:
        """
        Read values from a Google Sheet. Prioritizes instance attributes over method parameters.

        Args:
            spreadsheet_id: Fallback spreadsheet ID if instance attribute is None
            spreadsheet_range: Fallback range if instance attribute is None

        Returns:
            JSON of list of rows, where each row is a list of values
        """
        if not self.creds:
            return "Not authenticated. Call auth() first."

        # Prioritize instance attributes
        sheet_id = self.spreadsheet_id or spreadsheet_id
        sheet_range = self.spreadsheet_range or spreadsheet_range

        if not sheet_id or not sheet_range:
            return "Spreadsheet ID and range must be provided either in constructor or method call"

        try:
            result = self.service.spreadsheets().values().get(spreadsheetId=sheet_id, range=sheet_range).execute()  # type: ignore
            return json.dumps(result.get("values", []))

        except Exception as e:
            return f"Error reading Google Sheet: {e}"

    @authenticate
    def create_sheet(self, title: str) -> str:
        """
        Create a Google Sheet with a given title.

        Args:
            title: The title of the Google Sheet

        Returns:
            The ID of the created Google Sheet
        """
        if not self.creds:
            return "Not authenticated. Call auth() first."

        try:
            spreadsheet = {"properties": {"title": title}}

            spreadsheet = self.service.spreadsheets().create(body=spreadsheet, fields="spreadsheetId").execute()  # type: ignore
            spreadsheet_id = spreadsheet.get("spreadsheetId")

            return f"Spreadsheet created: https://docs.google.com/spreadsheets/d/{spreadsheet_id}"

        except Exception as e:
            return f"Error creating Google Sheet: {e}"

    @authenticate
    def update_sheet(
        self, data: List[List[Any]], spreadsheet_id: Optional[str] = None, range_name: Optional[str] = None
    ) -> str:
        """Updates a Google Sheet with the provided data.

        Note: This function can overwrite existing data in the sheet.
        User needs to ensure that the provided range correctly matches the data that needs to be updated.

        Args:
            data: The data to update the sheet with
            spreadsheet_id: The ID of the Google Sheet
            range_name: The range of the Google Sheet to update

        Returns:
            A message indicating the success or failure of the operation
        """
        if not self.creds:
            return "Not authenticated. Call auth() first."

        try:
            # Define the request body
            body = {"values": data}

            # Update the sheet
            self.service.spreadsheets().values().update(  # type: ignore
                spreadsheetId=spreadsheet_id,
                range=range_name,
                valueInputOption="RAW",
                body=body,
            ).execute()

            return f"Sheet updated successfully: {spreadsheet_id}"

        except Exception as e:
            return f"Error updating Google Sheet: {e}"

    @authenticate
    def create_duplicate_sheet(
        self, source_id: str, new_title: Optional[str] = None, copy_permissions: bool = True
    ) -> str:
        """Duplicate a Google Spreadsheet using the Google Drive API's copy feature.
        This ensures an exact duplicate including formatting and data.

        Note: Make sure your credentials include the drive scope 'https://www.googleapis.com/auth/drive'

        Args:
            source_id: The ID of the source spreadsheet.
            new_title: Optional new title for the duplicated spreadsheet. If not provided, the source title will be used.
            copy_permissions: Whether to copy the permissions from the source spreadsheet. Defaults to True.

        Returns:
            A link to the duplicated spreadsheet.
        """
        if not self.creds:
            return "Not authenticated. Call auth() first."

        if not self.service:
            return "Service not initialized"

        try:
            # Ensure the drive scope is included
            if "https://www.googleapis.com/auth/drive" not in self.scopes:
                self.scopes.append("https://www.googleapis.com/auth/drive")
                self._auth()  # Re-authenticate with updated scopes

            drive_service = build("drive", "v3", credentials=self.creds)

            # Use new_title if provided, otherwise fetch the title from the source spreadsheet
            if not new_title:
                source_sheet = self.service.spreadsheets().get(spreadsheetId=source_id).execute()
                new_title = source_sheet["properties"]["title"]

            body = {"name": new_title}
            new_file = drive_service.files().copy(fileId=source_id, body=body).execute()
            new_spreadsheet_id = new_file.get("id")

            # Copy permissions if requested
            if copy_permissions:
                # Get permissions from source file
                source_permissions = (
                    drive_service.permissions()
                    .list(fileId=source_id, fields="permissions(emailAddress,role,type)")
                    .execute()
                    .get("permissions", [])
                )

                # Apply each permission to the new file
                for permission in source_permissions:
                    # Skip the owner permission as it can't be transferred
                    if permission.get("role") == "owner":
                        continue

                    drive_service.permissions().create(
                        fileId=new_spreadsheet_id,
                        body={
                            "role": permission.get("role"),
                            "type": permission.get("type"),
                            "emailAddress": permission.get("emailAddress"),
                        },
                    ).execute()

            return f"Spreadsheet duplicated successfully: https://docs.google.com/spreadsheets/d/{new_spreadsheet_id}"
        except Exception as e:
            return f"Error duplicating spreadsheet via Drive API: {e}"
