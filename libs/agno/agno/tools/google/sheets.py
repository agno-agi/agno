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
from typing import Any, List, Optional, Union

from agno.tools.google.auth import get_current_creds, google_authenticate
from agno.tools.google.base import GoogleToolkit

try:
    from google.oauth2.credentials import Credentials
    from google.oauth2.service_account import Credentials as ServiceAccountCredentials
    from googleapiclient.discovery import build
except ImportError:
    raise ImportError(
        "`google-api-python-client` `google-auth-httplib2` `google-auth-oauthlib` not installed. Please install using `pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib`"
    )


authenticate = google_authenticate("sheets")


class GoogleSheetsTools(GoogleToolkit):
    api_name = "sheets"
    api_version = "v4"
    google_service_name = "sheets"

    SCOPE_LEVELS = {
        "read": "https://www.googleapis.com/auth/spreadsheets.readonly",
        "write": "https://www.googleapis.com/auth/spreadsheets",
    }

    def __init__(
        self,
        auth_config: Optional[Any] = None,
        store_token_in_db: bool = False,
        scopes: Optional[List[str]] = None,
        spreadsheet_id: Optional[str] = None,
        spreadsheet_range: Optional[str] = None,
        creds: Optional[Union[Credentials, ServiceAccountCredentials]] = None,
        creds_path: Optional[str] = None,
        token_path: Optional[str] = None,
        service_account_path: Optional[str] = None,
        oauth_port: int = 0,
        read_sheet: bool = True,
        create_sheet: bool = False,
        update_sheet: bool = False,
        create_duplicate_sheet: bool = False,
        # Backward compat aliases (deprecated)
        enable_read_sheet: Optional[bool] = None,
        enable_create_sheet: Optional[bool] = None,
        enable_update_sheet: Optional[bool] = None,
        enable_create_duplicate_sheet: Optional[bool] = None,
        all: bool = False,
        **kwargs,
    ):
        """Initialize GoogleSheetsTools with the specified configuration.

        Args:
            scopes (Optional[List[str]]): Custom OAuth scopes. If None, uses write scope by default.
            spreadsheet_id (Optional[str]): ID of the target spreadsheet.
            spreadsheet_range (Optional[str]): Range within the spreadsheet.
            creds (Optional[Credentials | ServiceAccountCredentials]): Pre-existing credentials.
            creds_path (Optional[str]): Path to credentials file.
            token_path (Optional[str]): Path to token file.
            service_account_path (Optional[str]): Path to a service account file.
            oauth_port (int): Port to use for OAuth authentication. Defaults to 0.
            read_sheet (bool): Enable reading from a sheet.
            create_sheet (bool): Enable creating a sheet.
            update_sheet (bool): Enable updating a sheet.
            create_duplicate_sheet (bool): Enable creating a duplicate sheet.
            enable_read_sheet (Optional[bool]): Deprecated alias for read_sheet.
            enable_create_sheet (Optional[bool]): Deprecated alias for create_sheet.
            enable_update_sheet (Optional[bool]): Deprecated alias for update_sheet.
            enable_create_duplicate_sheet (Optional[bool]): Deprecated alias for create_duplicate_sheet.
            all (bool): Enable all tools.
        """
        # Resolve deprecated aliases: explicit deprecated flag overrides new flag
        _read_sheet = enable_read_sheet if enable_read_sheet is not None else read_sheet
        _create_sheet = enable_create_sheet if enable_create_sheet is not None else create_sheet
        _update_sheet = enable_update_sheet if enable_update_sheet is not None else update_sheet
        _create_duplicate_sheet = (
            enable_create_duplicate_sheet if enable_create_duplicate_sheet is not None else create_duplicate_sheet
        )

        # Sheets-specific attributes
        self.spreadsheet_id = spreadsheet_id
        self.spreadsheet_range = spreadsheet_range

        # Determine required scopes based on operations if no custom scopes provided
        if scopes is None:
            resolved_scopes: List[str] = []
            if _read_sheet:
                resolved_scopes.append(self.SCOPE_LEVELS["read"])
            if _create_sheet or _update_sheet or _create_duplicate_sheet:
                resolved_scopes.append(self.SCOPE_LEVELS["write"])
            scopes = list(dict.fromkeys(resolved_scopes))
        else:
            # Validate that required scopes are present for requested operations
            if (_create_sheet or _update_sheet or _create_duplicate_sheet) and self.SCOPE_LEVELS["write"] not in scopes:
                raise ValueError(f"The scope {self.SCOPE_LEVELS['write']} is required for write operations")
            if _read_sheet and self.SCOPE_LEVELS["read"] not in scopes and self.SCOPE_LEVELS["write"] not in scopes:
                raise ValueError(
                    f"Either {self.SCOPE_LEVELS['read']} or {self.SCOPE_LEVELS['write']} is required for read operations"
                )

        tools: List[Any] = []
        if all or _read_sheet:
            tools.append(self.read_sheet)
        if all or _create_sheet:
            tools.append(self.create_sheet)
        if all or _update_sheet:
            tools.append(self.update_sheet)
        if all or _create_duplicate_sheet:
            tools.append(self.create_duplicate_sheet)

        super().__init__(
            name="google_sheets_tools",
            tools=tools,
            scopes=scopes,
            creds=creds,
            token_path=token_path,
            credentials_path=creds_path,
            service_account_path=service_account_path,
            auth_config=auth_config,
            store_token_in_db=store_token_in_db,
            oauth_port=oauth_port,
            **kwargs,
        )

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
        if not self.service:
            return "Not authenticated. Call auth() first."

        # Prioritize instance attributes
        sheet_id = self.spreadsheet_id or spreadsheet_id
        sheet_range = self.spreadsheet_range or spreadsheet_range

        if not sheet_id or not sheet_range:
            return "Spreadsheet ID and range must be provided either in constructor or method call"

        try:
            result = self.service.spreadsheets().values().get(spreadsheetId=sheet_id, range=sheet_range).execute()
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
        if not self.service:
            return "Not authenticated. Call auth() first."

        try:
            spreadsheet = {"properties": {"title": title}}

            spreadsheet = self.service.spreadsheets().create(body=spreadsheet, fields="spreadsheetId").execute()
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
        if not self.service:
            return "Not authenticated. Call auth() first."

        try:
            body = {"values": data}

            self.service.spreadsheets().values().update(
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
        if not self.service:
            return "Not authenticated. Call auth() first."

        creds = get_current_creds()
        if not creds:
            return "Not authenticated. Call auth() first."

        try:
            # Ensure the drive scope is included
            if "https://www.googleapis.com/auth/drive" not in self.scopes:
                return "Drive scope required. Add 'https://www.googleapis.com/auth/drive' to scopes."

            drive_service = build("drive", "v3", credentials=creds)

            # Use new_title if provided, otherwise fetch the title from the source spreadsheet
            if not new_title:
                source_sheet = self.service.spreadsheets().get(spreadsheetId=source_id).execute()
                new_title = source_sheet["properties"]["title"]

            body = {"name": new_title}
            new_file = drive_service.files().copy(fileId=source_id, body=body).execute()
            new_spreadsheet_id = new_file.get("id")

            # Copy permissions if requested
            if copy_permissions:
                source_permissions = (
                    drive_service.permissions()
                    .list(fileId=source_id, fields="permissions(emailAddress,role,type)")
                    .execute()
                    .get("permissions", [])
                )

                for permission in source_permissions:
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
