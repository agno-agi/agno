import errno
import json
import os
import platform
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from agno.db.json import JsonDb


def test_json_db_round_trips_non_ascii_content(tmp_path):
    db = JsonDb(db_path=str(tmp_path))
    rows = [{"id": "unicode", "content": "Olá, 世界", "emoji": "✅"}]

    db._write_json_file("unicode_rows", rows)

    assert db._read_json_file("unicode_rows") == rows


def test_json_db_atomic_write_preserves_table_on_serialization_failure(tmp_path):
    db = JsonDb(db_path=str(tmp_path))
    initial_rows = [{"id": "saved_session", "name": "important data"}]
    db._write_json_file("sessions", initial_rows)

    table_path = Path(tmp_path) / "sessions.json"
    original_bytes = table_path.read_bytes()

    # Attempt to write an object that fails serialization mid-stream or raises
    with (
        patch("agno.db.json.json_db.json.dump", side_effect=TypeError("Non-serializable object")),
        pytest.raises(TypeError),
    ):
        db._write_json_file("sessions", [{"id": "bad", "obj": object()}])

    # Destination table must be completely intact and identical
    assert table_path.read_bytes() == original_bytes
    assert db._read_json_file("sessions") == initial_rows

    # No leftover temporary files in directory
    temp_files = list(Path(tmp_path).glob(".sessions_*.tmp"))
    assert temp_files == []


def test_json_db_atomic_write_preserves_table_on_io_error(tmp_path):
    db = JsonDb(db_path=str(tmp_path))
    initial_rows = [{"id": "saved_session", "name": "important data"}]
    db._write_json_file("sessions", initial_rows)

    table_path = Path(tmp_path) / "sessions.json"
    original_bytes = table_path.read_bytes()

    # Simulate disk full (ENOSPC) during write
    with patch("agno.db.json.json_db.json.dump", side_effect=OSError(errno.ENOSPC, "No space left on device")):
        with pytest.raises(OSError) as exc_info:
            db._write_json_file("sessions", [{"id": "new_session", "data": "huge"}])
        assert exc_info.value.errno == errno.ENOSPC

    # Destination table must be completely intact
    assert table_path.read_bytes() == original_bytes
    assert db._read_json_file("sessions") == initial_rows

    # Temporary staging file was cleaned up
    temp_files = list(Path(tmp_path).glob(".sessions_*.tmp"))
    assert temp_files == []


@pytest.mark.skipif(
    platform.system() == "Windows",
    reason="Native RLIMIT_FSIZE is POSIX-only",
)
def test_json_db_atomic_write_preserves_table_on_native_write_failure(tmp_path):
    # Runs in a separate process so RLIMIT_FSIZE only applies to the test subprocess
    repo_libs_agno = str(Path(__file__).resolve().parents[3])
    script = f"""
import sys
sys.path.insert(0, r"{repo_libs_agno}")

import errno
import resource
import signal
from pathlib import Path
from agno.db.json import JsonDb
from agno.session import AgentSession

db = JsonDb(db_path=r"{tmp_path}")
session = AgentSession(
    session_id="saved",
    agent_id="agent",
    session_data={{"session_name": "last successful save"}},
)
db.upsert_session(session)

table = Path(r"{tmp_path}") / f"{{db.session_table_name}}.json"
previous = table.read_bytes()

signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
resource.setrlimit(
    resource.RLIMIT_FSIZE,
    (len(previous) + 64, len(previous) + 64),
)
try:
    db.upsert_session(
        AgentSession(
            session_id="new",
            agent_id="agent",
            session_data={{"session_name": "x" * 8192}},
        )
    )
except OSError as error:
    assert error.errno == errno.EFBIG
else:
    raise AssertionError("Expected native EFBIG")

assert table.read_bytes() == previous, "Failed save destroyed the last successful table"
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[3])
    res = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, env=env, check=False)
    assert res.returncode == 0, f"Subprocess failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"


@pytest.mark.skipif(platform.system() == "Windows", reason="POSIX permissions only")
def test_json_db_atomic_write_preserves_file_permissions(tmp_path):
    db = JsonDb(db_path=str(tmp_path))
    db._write_json_file("secured", [{"version": 1}])

    file_path = Path(tmp_path) / "secured.json"
    os.chmod(file_path, 0o600)

    # Overwrite
    db._write_json_file("secured", [{"version": 2}])

    mode = file_path.stat().st_mode & 0o777
    assert mode == 0o600


def test_json_db_read_creates_empty_file_atomically_if_not_found(tmp_path):
    db = JsonDb(db_path=str(tmp_path))
    result = db._read_json_file("new_table", create_table_if_not_found=True)

    assert result == []
    file_path = Path(tmp_path) / "new_table.json"
    assert file_path.exists()
    assert json.loads(file_path.read_text(encoding="utf-8")) == []
