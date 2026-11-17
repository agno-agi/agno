"""Real Docker destruction/replacement recovery, without model credentials."""

import os
from uuid import uuid4

import pytest

from agno.sandbox import SandboxError
from agno.sandbox.docker import DockerCheckpointTransfer, DockerSandbox

IMAGE = os.environ.get("AGNO_TEST_DOCKER_IMAGE")
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not IMAGE, reason="Set AGNO_TEST_DOCKER_IMAGE for real checkpoint transport"),
]


async def test_destroy_and_restore_all_declared_files(tmp_path, checkpoint_store):
    provider = DockerSandbox(IMAGE, namespace="transfer-" + uuid4().hex, memory_mb=512, workspace_mb=32)
    first = await provider.acreate("session", agent_id="coder")
    second = None
    transfer = DockerCheckpointTransfer(provider, checkpoint_store)
    try:
        script = """
from pathlib import Path
import sqlite3
Path('app.py').write_text('def add(a, b): return a + b\\n')
Path('test_app.py').write_text('import unittest\\nfrom app import add\\nclass TestApp(unittest.TestCase):\\n def test_add(self): self.assertEqual(add(2, 3), 5)\\n')
Path('.gitignore').write_text('ignored\\n')
Path('ignored').write_text('ignored data')
Path('untracked').write_bytes(bytes(range(256)))
Path('link').symlink_to('ignored')
Path('artifact.txt').write_text('test output')
native=Path('/runtime/native/codex')
native.mkdir(parents=True)
(native/'auth.json').write_text('must not checkpoint')
(native/'thread.jsonl').write_text('{"fact":"remember me"}\\n')
with sqlite3.connect('app.db') as db:
 db.execute('create table data(value text)')
 db.execute("insert into data values ('durable')")
"""
        assert (await provider.aexec(first, ["python", "-c", script])).exit_code == 0
        reference = await transfer.acapture(first, state={"run_id": "r", "conversation": ["remember me"]})
        assert (await provider.aget(first.provider_ref)).state == "running"
        await provider.adestroy(first)
        assert await provider.aget(first.provider_ref) is None
        second = await provider.acreate("session", agent_id="coder", generation=2)
        state = await DockerCheckpointTransfer(provider, checkpoint_store).arestore(second, reference)
        assert state == {"run_id": "r", "conversation": ["remember me"]}
        result = await provider.aexec(second, ["python", "-m", "unittest", "discover", "-v"])
        assert result.exit_code == 0 and "OK" in result.stderr, result
        script = """
from pathlib import Path
import sqlite3,os
assert Path('untracked').read_bytes() == bytes(range(256))
assert Path('link').read_text() == 'ignored data'
assert Path('artifact.txt').read_text() == 'test output'
assert not Path('/runtime/native/codex/auth.json').exists()
assert 'remember me' in Path('/runtime/native/codex/thread.jsonl').read_text()
assert sqlite3.connect('app.db').execute('select value from data').fetchone()[0] == 'durable'
assert Path('app.py').stat().st_uid == os.getuid() == 1000
Path('app.py').write_text(Path('app.py').read_text() + '# writable after restore\\n')
"""
        result = await provider.aexec(second, ["python", "-c", script])
        assert result.exit_code == 0, result.stderr
        with pytest.raises(SandboxError, match="empty"):
            await transfer.arestore(second, reference)
    finally:
        await provider.adestroy(first)
        if second is not None:
            await provider.adestroy(second)
    assert await provider._volume(first.name + "-workspace") is None
    assert await provider._volume(first.name + "-runtime") is None


async def test_failed_capture_resumes_compute_and_preserves_previous_checkpoint(
    tmp_path, monkeypatch, checkpoint_store
):
    provider = DockerSandbox(IMAGE, namespace="transfer-failure-" + uuid4().hex, memory_mb=256)
    handle = await provider.acreate("s", agent_id="a")
    store = checkpoint_store
    (tmp_path / "scratch").mkdir()
    transfer = DockerCheckpointTransfer(provider, store, scratch=tmp_path / "scratch")
    try:
        assert (await provider.aexec(handle, ["sh", "-c", "echo first > file"])).exit_code == 0
        reference = await transfer.acapture(handle, state={"run": "first"})

        async def fail(*args, **kwargs):
            raise OSError("injected disk full")

        monkeypatch.setattr(transfer, "_copy", fail)
        with pytest.raises(OSError, match="disk full"):
            await transfer.acapture(handle, state={"run": "second"})
        assert (await provider.aget(handle.provider_ref)).state == "running"
        store.verify(reference)
        assert not list((tmp_path / "scratch").iterdir())
    finally:
        await provider.adestroy(handle)


async def test_partial_restore_is_stopped(tmp_path, monkeypatch, checkpoint_store):
    provider = DockerSandbox(IMAGE, namespace="restore-failure-" + uuid4().hex, memory_mb=256)
    first = await provider.acreate("s", agent_id="a")
    second = None
    transfer = DockerCheckpointTransfer(provider, checkpoint_store)
    try:
        reference = await transfer.acapture(first, state={})
        second = await provider.acreate("s", agent_id="a", generation=2)
        original = transfer._copy
        calls = []

        async def fail_second(*args, **kwargs):
            calls.append(True)
            if len(calls) == 2:
                raise OSError("interrupted native restore")
            return await original(*args, **kwargs)

        monkeypatch.setattr(transfer, "_copy", fail_second)
        with pytest.raises(OSError, match="interrupted"):
            await transfer.arestore(second, reference)
        assert (await provider.aget(second.provider_ref)).state == "exited"
    finally:
        await provider.adestroy(first)
        if second is not None:
            await provider.adestroy(second)


async def test_archive_transfer_exceeds_command_output_limit_without_buffering_whole_object(tmp_path, checkpoint_store):
    provider = DockerSandbox(IMAGE, namespace="large-transfer-" + uuid4().hex, memory_mb=256, workspace_mb=64)
    handle = await provider.acreate("s", agent_id="a")
    transfer = DockerCheckpointTransfer(provider, checkpoint_store)
    try:
        result = await provider.aexec(
            # Random bytes stay large after compression, so the stored object still exceeds the output limit.
            handle,
            ["python", "-c", "import os; open('large', 'wb').write(os.urandom(40 * 1024 * 1024))"],
        )
        assert result.exit_code == 0
        reference = await transfer.acapture(handle, state={"large": True})
        assert reference.size > 40 * 1024 * 1024
        await transfer.store.averify(reference)
    finally:
        await provider.adestroy(handle)
