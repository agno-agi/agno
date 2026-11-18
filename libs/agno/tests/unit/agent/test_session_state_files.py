from unittest.mock import MagicMock
from agno.agent._init import _initialize_session_state

def test_initialize_session_state_with_files():
    session_state = {}
    mock_file1 = MagicMock()
    mock_file1.name = "test_doc.pdf"
    mock_file1.id = "file_123"

    mock_file2 = MagicMock()
    mock_file2.name = "data.csv"
    mock_file2.id = "file_456"

    _initialize_session_state(
        session_state,
        user_id="user_1",
        session_id="session_1",
        run_id="run_1",
        files=[mock_file1, mock_file2],
    )

    assert "files" in session_state
    assert session_state["files"] == [
        {"filename": "test_doc.pdf", "file_id": "file_123"},
        {"filename": "data.csv", "file_id": "file_456"},
    ]

def test_initialize_session_state_files_deduplication():
    session_state = {"files": [{"filename": "existing.txt", "file_id": "file_0"}]}
    mock_file = MagicMock()
    mock_file.name = "existing.txt"
    mock_file.id = "file_0"

    _initialize_session_state(
        session_state,
        files=[mock_file],
    )

    assert len(session_state["files"]) == 1
    assert session_state["files"][0] == {"filename": "existing.txt", "file_id": "file_0"}
