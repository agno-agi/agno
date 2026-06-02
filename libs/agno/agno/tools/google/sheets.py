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
from typing import Any, Dict, List, Optional, Union

from agno.agent.agent import Agent
from agno.run.base import RunContext
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

    default_scopes: Dict[str, str] = {
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
        # Basic operations
        read_sheet: bool = True,
        create_sheet: bool = False,
        update_sheet: bool = False,
        create_duplicate_sheet: bool = False,
        # Enterprise features
        append_rows: bool = False,
        get_spreadsheet_info: bool = False,
        add_sheet_tab: bool = False,
        delete_sheet_tab: bool = False,
        batch_update_values: bool = False,
        format_cells: bool = False,
        freeze_rows_columns: bool = False,
        auto_resize_columns: bool = False,
        clear_range: bool = False,
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

        # Determine which enterprise features need write scope
        write_features = (
            _create_sheet
            or _update_sheet
            or _create_duplicate_sheet
            or append_rows
            or add_sheet_tab
            or delete_sheet_tab
            or batch_update_values
            or format_cells
            or freeze_rows_columns
            or auto_resize_columns
            or clear_range
        )
        read_only_features = _read_sheet or get_spreadsheet_info

        # Determine required scopes based on operations if no custom scopes provided
        if scopes is None:
            resolved_scopes: List[str] = []
            if read_only_features:
                resolved_scopes.append(self.default_scopes["read"])
            if write_features:
                resolved_scopes.append(self.default_scopes["write"])
            scopes = list(dict.fromkeys(resolved_scopes))
        else:
            # Validate that required scopes are present for requested operations
            if write_features and self.default_scopes["write"] not in scopes:
                raise ValueError(f"The scope {self.default_scopes['write']} is required for write operations")
            if (
                read_only_features
                and self.default_scopes["read"] not in scopes
                and self.default_scopes["write"] not in scopes
            ):
                raise ValueError(
                    f"Either {self.default_scopes['read']} or {self.default_scopes['write']} is required for read operations"
                )

        tools: List[Any] = []
        # Basic operations
        if all or _read_sheet:
            tools.append(self.read_sheet)
        if all or _create_sheet:
            tools.append(self.create_sheet)
        if all or _update_sheet:
            tools.append(self.update_sheet)
        if all or _create_duplicate_sheet:
            tools.append(self.create_duplicate_sheet)
        # Enterprise features
        if all or append_rows:
            tools.append(self.append_rows)
        if all or get_spreadsheet_info:
            tools.append(self.get_spreadsheet_info)
        if all or add_sheet_tab:
            tools.append(self.add_sheet_tab)
        if all or delete_sheet_tab:
            tools.append(self.delete_sheet_tab)
        if all or batch_update_values:
            tools.append(self.batch_update_values)
        if all or format_cells:
            tools.append(self.format_cells)
        if all or freeze_rows_columns:
            tools.append(self.freeze_rows_columns)
        if all or auto_resize_columns:
            tools.append(self.auto_resize_columns)
        if all or clear_range:
            tools.append(self.clear_range)

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
    def read_sheet(
        self,
        agent: Agent,
        run_context: RunContext,
        spreadsheet_id: Optional[str] = None,
        spreadsheet_range: Optional[str] = None,
    ) -> str:
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
    def create_sheet(self, agent: Agent, run_context: RunContext, title: str) -> str:
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
        self,
        agent: Agent,
        run_context: RunContext,
        data: List[List[Any]],
        spreadsheet_id: Optional[str] = None,
        range_name: Optional[str] = None,
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
        self,
        agent: Agent,
        run_context: RunContext,
        source_id: str,
        new_title: Optional[str] = None,
        copy_permissions: bool = True,
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

    @authenticate
    def append_rows(
        self,
        agent: Agent,
        run_context: RunContext,
        data: List[List[Any]],
        spreadsheet_id: str,
        sheet_name: str = "Sheet1",
    ) -> str:
        """Append rows to the end of existing data in a sheet.

        Unlike update_sheet, this finds the next empty row and adds data there
        without overwriting existing content.

        Args:
            data: Rows to append, e.g. [["Name", "Email"], ["Alice", "alice@example.com"]]
            spreadsheet_id: The spreadsheet ID
            sheet_name: The sheet tab name (default: "Sheet1")

        Returns:
            Number of rows appended and the range updated
        """
        if not self.service:
            return "Not authenticated. Call auth() first."

        try:
            result = (
                self.service.spreadsheets()
                .values()
                .append(
                    spreadsheetId=spreadsheet_id,
                    range=f"{sheet_name}!A:Z",
                    valueInputOption="USER_ENTERED",
                    insertDataOption="INSERT_ROWS",
                    body={"values": data},
                )
                .execute()
            )

            updates = result.get("updates", {})
            rows = updates.get("updatedRows", len(data))
            updated_range = updates.get("updatedRange", "")

            return f"Appended {rows} rows to {updated_range}"

        except Exception as e:
            return f"Error appending rows: {e}"

    @authenticate
    def get_spreadsheet_info(
        self,
        agent: Agent,
        run_context: RunContext,
        spreadsheet_id: str,
    ) -> str:
        """Get metadata about a spreadsheet including all sheet names and row counts.

        Args:
            spreadsheet_id: The spreadsheet ID

        Returns:
            JSON with title, sheets (name, row count, column count for each)
        """
        if not self.service:
            return "Not authenticated. Call auth() first."

        try:
            result = (
                self.service.spreadsheets()
                .get(
                    spreadsheetId=spreadsheet_id,
                    fields="properties.title,sheets(properties(sheetId,title,gridProperties))",
                )
                .execute()
            )

            info = {
                "title": result.get("properties", {}).get("title", ""),
                "spreadsheet_id": spreadsheet_id,
                "url": f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}",
                "sheets": [],
            }

            for sheet in result.get("sheets", []):
                props = sheet.get("properties", {})
                grid = props.get("gridProperties", {})
                info["sheets"].append(
                    {
                        "name": props.get("title", ""),
                        "sheet_id": props.get("sheetId"),
                        "rows": grid.get("rowCount", 0),
                        "columns": grid.get("columnCount", 0),
                    }
                )

            return json.dumps(info, indent=2)

        except Exception as e:
            return f"Error getting spreadsheet info: {e}"

    @authenticate
    def add_sheet_tab(
        self,
        agent: Agent,
        run_context: RunContext,
        spreadsheet_id: str,
        title: str,
    ) -> str:
        """Add a new sheet tab to an existing spreadsheet.

        Args:
            spreadsheet_id: The spreadsheet ID
            title: Name for the new sheet tab

        Returns:
            The new sheet's ID and name
        """
        if not self.service:
            return "Not authenticated. Call auth() first."

        try:
            request = {"requests": [{"addSheet": {"properties": {"title": title}}}]}

            result = (
                self.service.spreadsheets()
                .batchUpdate(
                    spreadsheetId=spreadsheet_id,
                    body=request,
                )
                .execute()
            )

            replies = result.get("replies", [{}])
            new_sheet = replies[0].get("addSheet", {}).get("properties", {})

            return f"Added sheet '{new_sheet.get('title')}' (ID: {new_sheet.get('sheetId')})"

        except Exception as e:
            return f"Error adding sheet tab: {e}"

    @authenticate
    def delete_sheet_tab(
        self,
        agent: Agent,
        run_context: RunContext,
        spreadsheet_id: str,
        sheet_id: int,
    ) -> str:
        """Delete a sheet tab from a spreadsheet.

        Args:
            spreadsheet_id: The spreadsheet ID
            sheet_id: The numeric sheet ID (from get_spreadsheet_info)

        Returns:
            Confirmation message
        """
        if not self.service:
            return "Not authenticated. Call auth() first."

        try:
            request = {"requests": [{"deleteSheet": {"sheetId": sheet_id}}]}

            self.service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body=request,
            ).execute()

            return f"Deleted sheet with ID {sheet_id}"

        except Exception as e:
            return f"Error deleting sheet tab: {e}"

    @authenticate
    def batch_update_values(
        self,
        agent: Agent,
        run_context: RunContext,
        spreadsheet_id: str,
        updates: List[Dict[str, Any]],
    ) -> str:
        """Update multiple ranges in a single API call.

        More efficient than multiple update_sheet calls.

        Args:
            spreadsheet_id: The spreadsheet ID
            updates: List of {"range": "Sheet1!A1:B2", "values": [[1, 2], [3, 4]]}

        Returns:
            Summary of updates applied
        """
        if not self.service:
            return "Not authenticated. Call auth() first."

        try:
            body = {
                "valueInputOption": "USER_ENTERED",
                "data": updates,
            }

            result = (
                self.service.spreadsheets()
                .values()
                .batchUpdate(
                    spreadsheetId=spreadsheet_id,
                    body=body,
                )
                .execute()
            )

            total = result.get("totalUpdatedCells", 0)
            ranges = result.get("totalUpdatedSheets", len(updates))

            return f"Updated {total} cells across {ranges} ranges"

        except Exception as e:
            return f"Error in batch update: {e}"

    @authenticate
    def format_cells(
        self,
        agent: Agent,
        run_context: RunContext,
        spreadsheet_id: str,
        sheet_id: int,
        start_row: int,
        start_col: int,
        end_row: int,
        end_col: int,
        bold: Optional[bool] = None,
        italic: Optional[bool] = None,
        font_size: Optional[int] = None,
        background_color: Optional[Dict[str, float]] = None,
        text_color: Optional[Dict[str, float]] = None,
        horizontal_alignment: Optional[str] = None,
        number_format: Optional[str] = None,
    ) -> str:
        """Apply formatting to a range of cells.

        Args:
            spreadsheet_id: The spreadsheet ID
            sheet_id: Numeric sheet ID (from get_spreadsheet_info)
            start_row: Starting row (0-indexed)
            start_col: Starting column (0-indexed)
            end_row: Ending row (exclusive)
            end_col: Ending column (exclusive)
            bold: Make text bold
            italic: Make text italic
            font_size: Font size in points
            background_color: RGB dict like {"red": 1.0, "green": 0.9, "blue": 0.8}
            text_color: RGB dict for text color
            horizontal_alignment: "LEFT", "CENTER", or "RIGHT"
            number_format: Format pattern like "#,##0.00" or "0%"

        Returns:
            Confirmation message
        """
        if not self.service:
            return "Not authenticated. Call auth() first."

        try:
            cell_format: Dict[str, Any] = {}
            fields = []

            if bold is not None or italic is not None or font_size is not None:
                text_format: Dict[str, Any] = {}
                if bold is not None:
                    text_format["bold"] = bold
                    fields.append("userEnteredFormat.textFormat.bold")
                if italic is not None:
                    text_format["italic"] = italic
                    fields.append("userEnteredFormat.textFormat.italic")
                if font_size is not None:
                    text_format["fontSize"] = font_size
                    fields.append("userEnteredFormat.textFormat.fontSize")
                cell_format["textFormat"] = text_format

            if background_color is not None:
                cell_format["backgroundColor"] = background_color
                fields.append("userEnteredFormat.backgroundColor")

            if text_color is not None:
                if "textFormat" not in cell_format:
                    cell_format["textFormat"] = {}
                cell_format["textFormat"]["foregroundColor"] = text_color
                fields.append("userEnteredFormat.textFormat.foregroundColor")

            if horizontal_alignment is not None:
                cell_format["horizontalAlignment"] = horizontal_alignment
                fields.append("userEnteredFormat.horizontalAlignment")

            if number_format is not None:
                cell_format["numberFormat"] = {"type": "NUMBER", "pattern": number_format}
                fields.append("userEnteredFormat.numberFormat")

            if not fields:
                return "No formatting options specified"

            request = {
                "requests": [
                    {
                        "repeatCell": {
                            "range": {
                                "sheetId": sheet_id,
                                "startRowIndex": start_row,
                                "endRowIndex": end_row,
                                "startColumnIndex": start_col,
                                "endColumnIndex": end_col,
                            },
                            "cell": {"userEnteredFormat": cell_format},
                            "fields": ",".join(fields),
                        }
                    }
                ]
            }

            self.service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body=request,
            ).execute()

            return f"Applied formatting to rows {start_row}-{end_row}, columns {start_col}-{end_col}"

        except Exception as e:
            return f"Error formatting cells: {e}"

    @authenticate
    def freeze_rows_columns(
        self,
        agent: Agent,
        run_context: RunContext,
        spreadsheet_id: str,
        sheet_id: int,
        frozen_rows: int = 0,
        frozen_columns: int = 0,
    ) -> str:
        """Freeze rows and/or columns in a sheet (for headers).

        Args:
            spreadsheet_id: The spreadsheet ID
            sheet_id: Numeric sheet ID
            frozen_rows: Number of rows to freeze from top (0 to unfreeze)
            frozen_columns: Number of columns to freeze from left (0 to unfreeze)

        Returns:
            Confirmation message
        """
        if not self.service:
            return "Not authenticated. Call auth() first."

        try:
            request = {
                "requests": [
                    {
                        "updateSheetProperties": {
                            "properties": {
                                "sheetId": sheet_id,
                                "gridProperties": {
                                    "frozenRowCount": frozen_rows,
                                    "frozenColumnCount": frozen_columns,
                                },
                            },
                            "fields": "gridProperties.frozenRowCount,gridProperties.frozenColumnCount",
                        }
                    }
                ]
            }

            self.service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body=request,
            ).execute()

            parts = []
            if frozen_rows > 0:
                parts.append(f"{frozen_rows} row(s)")
            if frozen_columns > 0:
                parts.append(f"{frozen_columns} column(s)")

            if parts:
                return f"Froze {' and '.join(parts)}"
            return "Unfroze all rows and columns"

        except Exception as e:
            return f"Error freezing rows/columns: {e}"

    @authenticate
    def auto_resize_columns(
        self,
        agent: Agent,
        run_context: RunContext,
        spreadsheet_id: str,
        sheet_id: int,
        start_column: int = 0,
        end_column: Optional[int] = None,
    ) -> str:
        """Auto-resize columns to fit their content.

        Args:
            spreadsheet_id: The spreadsheet ID
            sheet_id: Numeric sheet ID
            start_column: First column to resize (0-indexed)
            end_column: Last column to resize (exclusive, None = all)

        Returns:
            Confirmation message
        """
        if not self.service:
            return "Not authenticated. Call auth() first."

        try:
            dimension_range: Dict[str, Any] = {
                "sheetId": sheet_id,
                "dimension": "COLUMNS",
                "startIndex": start_column,
            }
            if end_column is not None:
                dimension_range["endIndex"] = end_column

            request = {"requests": [{"autoResizeDimensions": {"dimensions": dimension_range}}]}

            self.service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body=request,
            ).execute()

            if end_column:
                return f"Auto-resized columns {start_column} to {end_column - 1}"
            return f"Auto-resized columns starting from {start_column}"

        except Exception as e:
            return f"Error auto-resizing columns: {e}"

    @authenticate
    def clear_range(
        self,
        agent: Agent,
        run_context: RunContext,
        spreadsheet_id: str,
        range_name: str,
    ) -> str:
        """Clear all values in a range (keeps formatting).

        Args:
            spreadsheet_id: The spreadsheet ID
            range_name: A1 notation range like "Sheet1!A1:D10"

        Returns:
            Confirmation message
        """
        if not self.service:
            return "Not authenticated. Call auth() first."

        try:
            self.service.spreadsheets().values().clear(
                spreadsheetId=spreadsheet_id,
                range=range_name,
            ).execute()

            return f"Cleared values in {range_name}"

        except Exception as e:
            return f"Error clearing range: {e}"
