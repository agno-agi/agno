"""Credential-free filesystem checkpoint/recovery; no running process is captured."""

import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

from agno.sandbox.checkpoint import CheckpointArchive, FileCheckpointStore

with TemporaryDirectory() as directory:
    root = Path(directory)
    workspace, native = root / "workspace", root / "native"
    workspace.mkdir()
    native.mkdir()
    (workspace / ".gitignore").write_text("ignored.txt\n")
    (workspace / "ignored.txt").write_text("preserve me")
    (native / "transcript.jsonl").write_text('{"message":"remember this"}\n')
    (native / "auth.json").write_text("do not checkpoint credentials")

    archive = CheckpointArchive()
    archive.capture(
        {"workspace": workspace, "native": native},
        root / "checkpoint.tar",
        state={
            "run_id": "example",
            "native_id": "native-example",
            "conversation": ["remember this"],
        },
        exclude=["native/auth.json"],
    )
    store = FileCheckpointStore(root / "objects")
    reference = store.put(root / "checkpoint.tar")
    shutil.rmtree(workspace)
    shutil.rmtree(native)
    (root / "checkpoint.tar").unlink()

    # Another coordinator instance uses the same durable object directory.
    recovered_store = FileCheckpointStore(root / "objects")
    state = recovered_store.restore(reference, root / "replacement")
    assert (root / "replacement/workspace/ignored.txt").read_text() == "preserve me"
    assert (
        root / "replacement/native/transcript.jsonl"
    ).read_text() == '{"message":"remember this"}\n'
    assert not (root / "replacement/native/auth.json").exists()
    assert state["conversation"] == ["remember this"]
    print(
        "Restored conversation metadata, native files and ignored workspace data from one immutable checkpoint."
    )
