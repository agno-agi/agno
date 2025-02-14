"""Unit tests for GoogleSheetsTools class."""

import json
from unittest.mock import MagicMock, Mock, patch

import pytest
from google.oauth2.credentials import Credentials

from agno.tools.googlesheets import GoogleSheetsTools


@pytest.fixture
def mock_credentials():
    """Mock Google OAuth2 credentials."""
    mock_creds = Mock(spec=Credentials)
    mock_creds.valid = True
    mock_creds.expired = False
    return mock_creds


@pytest.fixture
def mock_sheets_service():
    """Mock Google Sheets API service."""
    mock_service = MagicMock()
    return mock_service


@pytest.fixture
def sheets_tools(mock_credentials, mock_sheets_service):
    """Create GoogleSheetsTools instance with mocked dependencies."""
    with patch("agno.tools.googlesheets.build") as mock_build:
        mock_build.return_value = mock_sheets_service
        tools = GoogleSheetsTools(creds=mock_credentials)
        tools.service = mock_sheets_service
        return tools


# Initialization Tests
def test_init_with_default_scopes():
    """Test initialization with default scopes."""
    # Test read-only initialization
    read_tools = GoogleSheetsTools(read=True, create=False, update=False)
    assert read_tools.scopes == [GoogleSheetsTools.DEFAULT_SCOPES["read"]]

    # Test write operations initialization
    write_tools = GoogleSheetsTools(read=False, create=True, update=True)
    assert GoogleSheetsTools.DEFAULT_SCOPES["write"] in write_tools.scopes


def test_init_with_custom_scopes():
    """Test initialization with custom scopes."""
    custom_scopes = [GoogleSheetsTools.DEFAULT_SCOPES["read"]]
    tools = GoogleSheetsTools(scopes=custom_scopes, read=True, create=False, update=False)
    assert tools.scopes == custom_scopes


def test_init_with_invalid_scopes():
    """Test initialization with invalid scopes for requested operations."""
    read_only_scope = [GoogleSheetsTools.DEFAULT_SCOPES["read"]]
    with pytest.raises(ValueError, match="required for write operations"):
        GoogleSheetsTools(
            scopes=read_only_scope,
            read=True,
            create=True,  # Should raise error as write scope is missing
        )


def test_read_sheet(sheets_tools, mock_sheets_service):
    """Test reading from a sheet."""
    # Setup mock data
    mock_data = {"values": [["Header1", "Header2"], ["Value1", "Value2"]]}

    # Setup mock returns
    mock_sheets_service.spreadsheets().values().get().execute.return_value = mock_data

    # Execute test
    result = sheets_tools.read_sheet(spreadsheet_id="test_id", spreadsheet_range="Sheet1!A1:B2")
    # Verify the result
    parsed_result = json.loads(result)
    assert parsed_result == mock_data["values"]


def test_create_sheet(sheets_tools, mock_sheets_service):
    """Test creating a new sheet."""
    # Setup mock data
    mock_response = {"spreadsheetId": "new_sheet_id", "properties": {"title": "Test Sheet"}}

    # Setup mock chain
    mock_sheets_service.spreadsheets().create().execute.return_value = mock_response

    # Execute test
    result = sheets_tools.create_sheet("Test Sheet")

    # Verify the result
    assert "https://docs.google.com/spreadsheets/d/new_sheet_id" in result


def test_update_sheet(sheets_tools, mock_sheets_service):
    """Test updating a sheet."""
    # Setup mock data
    test_data = [["Updated1", "Updated2"], ["Updated3", "Updated4"]]
    mock_response = {"updatedCells": 4}

    # Setup mock chain
    mock_sheets_service.spreadsheets().values().update().execute.return_value = mock_response

    # Execute test
    result = sheets_tools.update_sheet(data=test_data, spreadsheet_id="test_id", range_name="Sheet1!A1:B2")

    # Execute test
    result = sheets_tools.update_sheet(data=test_data, spreadsheet_id="test_id", range_name="Sheet1!A1:B2")

    # Verify the result
    assert "Sheet updated successfully: test_id" in result


def test_create_duplicate_sheet(sheets_tools, mock_sheets_service):
    """Test duplicating a sheet."""
    # Setup mock data
    mock_source = {"properties": {"title": "Source Sheet"}, "sheets": [{"properties": {"title": "Sheet1"}}]}
    mock_values = {"values": [["Data1", "Data2"]]}
    mock_new_sheet = {"spreadsheetId": "new_id"}

    # Setup mock chain for getting source sheet
    mock_sheets_service.spreadsheets().get().execute.return_value = mock_source

    # Setup mock chain for getting values
    mock_sheets_service.spreadsheets().values().get().execute.return_value = mock_values

    # Setup mock chain for creating new sheet
    mock_sheets_service.spreadsheets().create().execute.return_value = mock_new_sheet

    # Execute test
    result = sheets_tools.create_duplicate_sheet(source_id="source_id")

    # Verify the result
    assert "https://docs.google.com/spreadsheets/d/new_id" in result


def test_error_handling(sheets_tools, mock_sheets_service):
    """Test error handling in sheets operations."""
    from googleapiclient.errors import HttpError

    # Setup mock chain for getting values

    mock_sheets_service.spreadsheets().get.side_effect = HttpError(
        resp=Mock(status=403), content=b'{"error": {"message": "Access Denied"}}'
    )

    # Execute test
    result = sheets_tools.read_sheet(spreadsheet_id="test_id", spreadsheet_range="A1:B2")

    assert "Error reading Google Sheet" in result
