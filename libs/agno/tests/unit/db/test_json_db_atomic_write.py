import errno
import json
import os
import subprocess
import sys
import threading
from unittest.mock import patch

import pytest

from agno.db.base import SessionType
from agno.db.json import JsonDb
from agno.session import AgentSession


def create_symlink(link, target, target_is_directory=False):
    try:
        link.symlink_to(target, target_is_directory=target_is_directory)
    except OSError as error:
        if os.name == "nt" and (getattr(error, "winerror", None) == 1314 or error.errno == errno.EPERM):
            pytest.skip("Windows symbolic-link creation privilege is unavailable")
        raise


def saved_table(tmp_path):
    db = JsonDb(db_path=str(tmp_path))
    db.upsert_session(AgentSession(session_id="saved", agent_id="agent", session_data={"session_name": "saved"}))
    table = tmp_path / f"{db.session_table_name}.json"
    return db, table, table.read_bytes()


@pytest.mark.parametrize("failure", ["serialize", "publish"])
def test_failed_session_save_preserves_table_and_removes_staging_file(tmp_path, failure):
    db, table, prior = saved_table(tmp_path)

    def fail_dump(data, handle, **kwargs):
        handle.write("[")
        raise OSError(errno.ENOSPC, "No space left on device")

    target = "agno.db.json.json_db.json.dump" if failure == "serialize" else "agno.db.json.json_db.os.replace"
    options = {"side_effect": fail_dump} if failure == "serialize" else {"side_effect": OSError(errno.EIO, "I/O error")}
    with patch(target, **options), pytest.raises(OSError):
        db.upsert_session(AgentSession(session_id="new", agent_id="agent"))

    assert table.read_bytes() == prior
    assert db.get_session("saved", session_type=SessionType.AGENT).session_id == "saved"
    assert list(tmp_path.iterdir()) == [table]


def test_session_save_publishes_complete_unicode_table(tmp_path):
    db, table, _ = saved_table(tmp_path)
    db.upsert_session(AgentSession(session_id="new", agent_id="agent", session_data={"session_name": "Olá, 世界"}))

    assert db.get_session("new", session_type=SessionType.AGENT).session_data["session_name"] == "Olá, 世界"
    assert len(json.loads(table.read_text(encoding="utf-8"))) == 2
    assert list(tmp_path.iterdir()) == [table]


@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
def test_session_save_preserves_existing_permissions(tmp_path):
    db, table, _ = saved_table(tmp_path)
    table.chmod(0o600)
    db.upsert_session(AgentSession(session_id="new", agent_id="agent"))

    assert table.stat().st_mode & 0o777 == 0o600


@pytest.mark.skipif(os.name == "nt", reason="Requires unprivileged POSIX permissions")
def test_read_only_table_is_not_replaced(tmp_path):
    if os.geteuid() == 0:
        pytest.skip("root can write a read-only table")
    db, table, prior = saved_table(tmp_path)
    table.chmod(0o400)
    try:
        with pytest.raises(PermissionError):
            db.upsert_session(AgentSession(session_id="new", agent_id="agent"))
        assert table.read_bytes() == prior
        assert list(tmp_path.iterdir()) == [table]
    finally:
        table.chmod(0o600)


def test_session_save_keeps_existing_table_symlink(tmp_path):
    db, table, _ = saved_table(tmp_path)
    target = tmp_path / "saved-table.json"
    table.rename(target)
    create_symlink(table, target.name)
    db.upsert_session(AgentSession(session_id="new", agent_id="agent"))

    assert table.is_symlink()
    assert len(json.loads(target.read_text(encoding="utf-8"))) == 2
    assert set(tmp_path.iterdir()) == {table, target}


@pytest.mark.skipif(os.name == "nt", reason="Requires POSIX RLIMIT_FSIZE")
def test_native_file_size_failure_preserves_saved_session(tmp_path):
    script = """
import errno
import resource
import signal
import sys
from pathlib import Path
from agno.db.base import SessionType
from agno.db.json import JsonDb
from agno.session import AgentSession

directory = Path(sys.argv[1])
db = JsonDb(db_path=str(directory))
db.upsert_session(AgentSession(session_id="saved", agent_id="agent"))
table = directory / f"{db.session_table_name}.json"
prior = table.read_bytes()
signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
resource.setrlimit(resource.RLIMIT_FSIZE, (len(prior) + 64, len(prior) + 64))
try:
    db.upsert_session(AgentSession(session_id="new", agent_id="agent", session_data={"value": "x" * 8192}))
except OSError as error:
    assert error.errno == errno.EFBIG
else:
    raise AssertionError("the native write must fail")
assert table.read_bytes() == prior
assert db.get_session("saved", session_type=SessionType.AGENT).session_id == "saved"
assert list(directory.iterdir()) == [table]
"""
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_session_save_follows_database_directory_symlink(tmp_path):
    target = tmp_path / "tables"
    target.mkdir()
    linked_directory = tmp_path / "linked"
    create_symlink(linked_directory, target, target_is_directory=True)
    db = JsonDb(db_path=str(linked_directory))
    db.upsert_session(AgentSession(session_id="saved", agent_id="agent"))

    assert linked_directory.is_symlink()
    assert db.get_session("saved", session_type=SessionType.AGENT).session_id == "saved"
    assert [file.name for file in target.iterdir()] == [f"{db.session_table_name}.json"]


@pytest.mark.skipif(os.name == "nt", reason="POSIX write-only permissions")
def test_write_only_table_can_still_be_written(tmp_path):
    db, table, _ = saved_table(tmp_path)
    table.chmod(0o200)
    try:
        db._write_json_file(db.session_table_name, [{"id": "new"}])
        assert table.stat().st_mode & 0o777 == 0o200
    finally:
        table.chmod(0o600)
    assert json.loads(table.read_text(encoding="utf-8")) == [{"id": "new"}]


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="POSIX named pipes")
def test_writer_does_not_replace_a_nonregular_table(tmp_path):
    db = JsonDb(db_path=str(tmp_path))
    table = tmp_path / "pipe.json"
    os.mkfifo(table)
    received = []

    def read_pipe():
        with table.open("r", encoding="utf-8") as pipe:
            received.append(json.load(pipe))

    reader = threading.Thread(target=read_pipe, daemon=True)
    reader.start()
    db._write_json_file("pipe", [{"id": "new"}])
    reader.join(timeout=2)

    assert not reader.is_alive()
    assert received == [[{"id": "new"}]]
    assert table.is_fifo()


def test_failed_exclusive_create_does_not_remove_another_staging_file(tmp_path):
    from types import SimpleNamespace

    db, table, prior = saved_table(tmp_path)
    staging = tmp_path / ".agno-json-collision.tmp"
    staging.write_text("another writer", encoding="utf-8")
    with patch("agno.db.json.json_db.uuid4", return_value=SimpleNamespace(hex="collision")):
        with pytest.raises(FileExistsError):
            db.upsert_session(AgentSession(session_id="new", agent_id="agent"))

    assert staging.read_text(encoding="utf-8") == "another writer"
    assert table.read_bytes() == prior


@pytest.mark.parametrize("error", [errno.EBUSY, errno.EXDEV, errno.EACCES])
def test_unreplaceable_table_is_written_in_place(tmp_path, error):
    db, table, _ = saved_table(tmp_path)
    with patch("agno.db.json.json_db.os.replace", side_effect=OSError(error, os.strerror(error))):
        db.upsert_session(AgentSession(session_id="new", agent_id="agent"))

    assert db.get_session("new", session_type=SessionType.AGENT).session_id == "new"
    assert list(tmp_path.iterdir()) == [table]


@pytest.mark.skipif(os.name == "nt", reason="Requires unprivileged POSIX permissions")
def test_read_only_directory_writes_existing_table_in_place(tmp_path):
    if os.geteuid() == 0:
        pytest.skip("root can write a read-only directory")
    db, table, _ = saved_table(tmp_path)
    tmp_path.chmod(0o555)
    try:
        db.upsert_session(AgentSession(session_id="new", agent_id="agent"))
    finally:
        tmp_path.chmod(0o755)

    assert db.get_session("new", session_type=SessionType.AGENT).session_id == "new"
    assert list(tmp_path.iterdir()) == [table]


def test_table_owned_by_another_user_is_written_in_place(tmp_path):
    db, table, _ = saved_table(tmp_path)
    with patch("agno.db.json.json_db.JsonDb._copy_table_metadata", side_effect=PermissionError(errno.EPERM, "denied")):
        db.upsert_session(AgentSession(session_id="new", agent_id="agent"))

    assert db.get_session("new", session_type=SessionType.AGENT).session_id == "new"
    assert list(tmp_path.iterdir()) == [table]


@pytest.mark.skipif(not hasattr(os, "chown"), reason="POSIX ownership")
def test_staging_file_takes_existing_owner(tmp_path):
    db, table, _ = saved_table(tmp_path)
    existing = table.stat()
    foreign = os.stat_result(
        (existing.st_mode, *existing[1:4], existing.st_uid + 1, existing.st_gid + 1, *existing[6:])
    )
    with patch("agno.db.json.json_db.os.chown") as chown:
        JsonDb._copy_table_metadata(table, foreign)

    chown.assert_called_once_with(table, existing.st_uid + 1, existing.st_gid + 1)


@pytest.mark.skipif(not hasattr(os, "geteuid") or os.geteuid() != 0, reason="Requires root")
def test_root_write_preserves_table_owner(tmp_path):
    db, table, _ = saved_table(tmp_path)
    os.chown(table, 1000, 1000)
    table.chmod(0o640)
    db.upsert_session(AgentSession(session_id="new", agent_id="agent"))

    assert (table.stat().st_uid, table.stat().st_gid) == (1000, 1000)
    assert table.stat().st_mode & 0o777 == 0o640


def test_table_creation_does_not_truncate_a_concurrently_published_table(tmp_path):
    db, table, prior = saved_table(tmp_path)
    real_open = open
    raced = []

    def open_after_publish(file, mode="r", *args, **kwargs):
        if mode == "r" and not raced:
            raced.append(True)
            raise FileNotFoundError(errno.ENOENT, "missing", str(file))
        return real_open(file, mode, *args, **kwargs)

    with patch("builtins.open", side_effect=open_after_publish):
        assert db._read_json_file(db.session_table_name) == []

    assert table.read_bytes() == prior


@pytest.mark.parametrize("error", [errno.EACCES, errno.EPERM, errno.EBUSY, errno.EXDEV])
def test_serialization_error_is_not_written_in_place(tmp_path, error):
    db, table, prior = saved_table(tmp_path)

    def fail_dump(data, handle, **kwargs):
        handle.write("[")
        raise OSError(error, os.strerror(error))

    with patch("agno.db.json.json_db.json.dump", side_effect=fail_dump), pytest.raises(OSError):
        db.upsert_session(AgentSession(session_id="new", agent_id="agent"))

    assert table.read_bytes() == prior
    assert list(tmp_path.iterdir()) == [table]
