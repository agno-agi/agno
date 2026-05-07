"""Reproduction tests for Bug #7823: GoogleDriveTools.search_files() drops the
Drive API `incompleteSearch` flag, masking partial allDrives search results.

These tests are designed to FAIL on the current code (proving the bug exists)
and PASS once PR #7824's patch is applied.

Reference:
- Issue: https://github.com/agno-agi/agno/issues/7823
- PR:    https://github.com/agno-agi/agno/pull/7824
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from google.oauth2.credentials import Credentials

from agno.tools.google.drive import GoogleDriveTools


@pytest.fixture
def mock_creds():
    creds = MagicMock(spec=Credentials)
    creds.valid = True
    creds.expired = False
    return creds


@pytest.fixture
def mock_service():
    return MagicMock()


@pytest.fixture
def all_drives_tools(mock_creds, mock_service):
    """allDrives-configured GoogleDriveTools — mirrors the canonical test fixture."""
    with (
        patch("agno.tools.google.drive.build") as mock_build,
        patch.object(GoogleDriveTools, "_auth", return_value=None),
    ):
        mock_build.return_value = mock_service
        tools = GoogleDriveTools(
            creds=mock_creds,
            corpora="allDrives",
            supports_all_drives=True,
            include_items_from_all_drives=True,
        )
        tools.service = mock_service
        return tools


# ---------------------------------------------------------------------------
# Bug #7823 reproduction tests — RED on main, GREEN after PR #7824
# ---------------------------------------------------------------------------


def test_repro_search_files_surfaces_incomplete_search(all_drives_tools):
    """Bug #7823: search_files() must surface incompleteSearch=True from Drive API.

    Drive sets incompleteSearch=true when an allDrives query could not search
    every drive. Currently the wrapper drops it, masking partial results.
    """
    all_drives_tools.service.files.return_value.list.return_value.execute.return_value = {
        "files": [],
        "incompleteSearch": True,
    }

    result = json.loads(all_drives_tools.search_files(query="name contains 'x'"))

    assert "incompleteSearch" in result, (
        "Bug #7823: search_files() drops the incompleteSearch flag from Drive API response"
    )
    assert result["incompleteSearch"] is True


def test_repro_search_files_requests_incomplete_search_in_field_mask(all_drives_tools):
    """Bug #7823: SEARCH_FIELDS must request incompleteSearch in Drive's field mask."""
    all_drives_tools.search_files(query="name contains 'x'")

    call_kwargs = all_drives_tools.service.files.return_value.list.call_args[1]
    fields = call_kwargs["fields"]

    assert "incompleteSearch" in fields, f"Bug #7823: SEARCH_FIELDS does not request incompleteSearch (got: {fields!r})"


# ---------------------------------------------------------------------------
# Phase 3: Robustness battery — edge cases basnijholt's single test misses
# ---------------------------------------------------------------------------


def test_search_files_default_when_field_absent(all_drives_tools):
    """Test #5: When Drive omits incompleteSearch (typical for corpora='user'),
    wrapper must default to False — not None, not KeyError."""
    all_drives_tools.service.files.return_value.list.return_value.execute.return_value = {
        "files": [],
        # No incompleteSearch key — Drive often omits it when False
    }

    result = json.loads(all_drives_tools.search_files(query="x"))

    assert "incompleteSearch" in result
    assert result["incompleteSearch"] is False


def test_search_files_explicit_false(all_drives_tools):
    """Test #6: When Drive explicitly returns incompleteSearch=False,
    wrapper must preserve the literal False (not coerce to None)."""
    all_drives_tools.service.files.return_value.list.return_value.execute.return_value = {
        "files": [],
        "incompleteSearch": False,
    }

    result = json.loads(all_drives_tools.search_files(query="x"))

    assert result["incompleteSearch"] is False
    assert result["incompleteSearch"] is not None


def test_list_files_also_surfaces_incomplete_search(all_drives_tools):
    """Test #7: list_files delegates to search_files — flag must propagate through both."""
    all_drives_tools.service.files.return_value.list.return_value.execute.return_value = {
        "files": [],
        "incompleteSearch": True,
    }

    result = json.loads(all_drives_tools.list_files())

    assert "incompleteSearch" in result
    assert result["incompleteSearch"] is True


def test_pagination_preserves_incomplete_search_per_page(all_drives_tools):
    """Test #8: Each page's incompleteSearch is independent and must flow through each call."""
    all_drives_tools.service.files.return_value.list.return_value.execute.side_effect = [
        {"files": [{"id": "1", "name": "a"}], "nextPageToken": "p2", "incompleteSearch": False},
        {"files": [{"id": "2", "name": "b"}], "incompleteSearch": True},
    ]

    page1 = json.loads(all_drives_tools.search_files(query="x"))
    page2 = json.loads(all_drives_tools.search_files(query="x", page_token="p2"))

    assert page1["incompleteSearch"] is False
    assert page2["incompleteSearch"] is True


def test_error_path_does_not_include_incomplete_search(all_drives_tools):
    """Test #9: When the API call raises, error JSON must not have a stale incompleteSearch."""
    all_drives_tools.service.files.return_value.list.side_effect = Exception("API error")

    result = json.loads(all_drives_tools.search_files(query="x"))

    assert "error" in result
    assert "incompleteSearch" not in result


async def test_async_search_files_surfaces_incomplete_search(all_drives_tools):
    """Test #11: asearch_files (async thread-wrapper) must surface the flag."""
    all_drives_tools.service.files.return_value.list.return_value.execute.return_value = {
        "files": [],
        "incompleteSearch": True,
    }

    result = json.loads(await all_drives_tools.asearch_files(query="x"))

    assert result["incompleteSearch"] is True


# ---------------------------------------------------------------------------
# Phase 4: HTTP-mock tier — real googleapiclient Discovery + URL/JSON paths
# ---------------------------------------------------------------------------


def test_http_mock_real_client_surfaces_incomplete_search(mock_creds):
    """Phase 4: real googleapiclient Discovery + URL building + JSON deserialization
    must accept incompleteSearch in the field mask and pass it through.

    Catches bugs the service-stub mocks can't see:
    - field-mask parsing/encoding by googleapiclient
    - JSON deserialization of Drive's response shape
    - whether the bundled Drive Discovery doc knows about incompleteSearch
    """
    from googleapiclient.discovery import build
    from googleapiclient.http import HttpMock

    http = HttpMock()
    http.data = json.dumps({"files": [], "incompleteSearch": True})

    real_service = build("drive", "v3", http=http, developerKey="dummy", static_discovery=True)

    with (
        patch("agno.tools.google.drive.build", return_value=real_service),
        patch.object(GoogleDriveTools, "_auth", return_value=None),
    ):
        tools = GoogleDriveTools(
            creds=mock_creds,
            corpora="allDrives",
            supports_all_drives=True,
            include_items_from_all_drives=True,
        )
        tools.service = real_service

    result = json.loads(tools.search_files(query="x"))

    assert result["incompleteSearch"] is True
    assert "incompleteSearch" in http.uri


# ---------------------------------------------------------------------------
# Phase 6: log_warning improvement — visibility for non-JSON-inspecting callers
# ---------------------------------------------------------------------------


def test_log_warning_emitted_when_incomplete_search_true(all_drives_tools):
    """Phase 6: log_warning must fire when Drive returns incompleteSearch=True
    so partial results are visible to operators without inspecting JSON."""
    all_drives_tools.service.files.return_value.list.return_value.execute.return_value = {
        "files": [],
        "incompleteSearch": True,
    }

    with patch("agno.tools.google.drive.log_warning") as mock_warn:
        all_drives_tools.search_files(query="x")

    assert mock_warn.called, "Expected log_warning when incompleteSearch=True"
    msg = mock_warn.call_args[0][0]
    assert "incomplete" in msg.lower()


def test_log_warning_not_emitted_when_incomplete_search_false(all_drives_tools):
    """Phase 6: no warning fires when incompleteSearch=False or absent."""
    all_drives_tools.service.files.return_value.list.return_value.execute.return_value = {
        "files": [],
        "incompleteSearch": False,
    }

    with patch("agno.tools.google.drive.log_warning") as mock_warn:
        all_drives_tools.search_files(query="x")

    assert not mock_warn.called, "Should not log warning when incompleteSearch=False"
