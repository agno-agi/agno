"""
Attachment staging: what lands in the workspace, and what is cleaned up
=======================================================================
Claude and Codex take attachments as files under <workspace>/.agno/uploads/<run_id>/,
named in the prompt, and remove them when the turn ends. This cookbook shows the
guarantees around that, with a ClaudeAgent:

1. A failed staging leaves nothing behind. The second attachment's write is made to
   fail (a simulation, no model call), and the first attachment is rolled back too.
2. A session continued on a replica with a different workspace restores earlier
   attachments under its own workspace and tells Claude the new paths; nothing is
   written into the other replica's directory.
3. A file Claude writes beside the attachment is removed with the run folder.
4. A symlinked uploads directory is refused before Claude is spawned, once, and is
   not retried.

Prerequisites: claude-agent-sdk and Claude authentication
Run: .venvs/demo/bin/python cookbook/frameworks/attachment_safety/attachment_staging.py
"""

import tempfile
from pathlib import Path

from agno.agents.claude import ClaudeAgent
from agno.db.sqlite import SqliteDb
from agno.media import File
from agno.run.base import RunStatus


def files_under(workspace: Path) -> list:
    return sorted(
        str(p.relative_to(workspace))
        for p in workspace.rglob("*")
        if p.is_file() and ".agno" in str(p)
    )


def make_agent(workspace: Path, db: SqliteDb, **kwargs) -> ClaudeAgent:
    return ClaudeAgent(
        id="attachments",
        model="claude-sonnet-4-6",
        cwd=str(workspace),
        db=db,
        system_prompt=f"You work in {workspace}. Answer in one line.",
        allowed_tools=["Read", "Write"],
        permission_mode="bypassPermissions",
        max_turns=4,
        **kwargs,
    )


def failed_staging_leaves_nothing(workspace: Path) -> None:
    from types import SimpleNamespace

    from agno.agents import _media

    print("1. The second attachment fails to write (simulated):")
    original, original_write = Path.open, Path.write_bytes

    def failing_open(path, *args, **kwargs):
        if path.name == "second.txt" and args and args[0] == "xb":
            raise OSError("simulated disk full")
        return original(path, *args, **kwargs)

    def failing_write(path, data):
        if path.name == "second.txt":
            raise OSError("simulated disk full")
        return original_write(path, data)

    Path.open, Path.write_bytes = failing_open, failing_write  # type: ignore[method-assign]
    try:
        _media.stage_media(
            workspace,
            "run-1",
            {
                "files": [
                    SimpleNamespace(filename="first.txt", content=b"a"),
                    SimpleNamespace(filename="second.txt", content=b"b"),
                ]
            },
        )
    except OSError as error:
        print(f"   staging raised: {error}")
    finally:
        Path.open, Path.write_bytes = original, original_write  # type: ignore[method-assign]
    print(f"   left under the workspace: {files_under(workspace)}")
    assert not (workspace / ".agno").exists()


def restore_on_another_replica(base: Path, db: SqliteDb) -> None:
    print("2. A later turn on a replica with a different workspace:")
    replica_a, replica_b = base / "replica-a", base / "replica-b"
    replica_a.mkdir()
    replica_b.mkdir()
    notes = File(
        content=b"owner: Priya Raman\ncodename: tangerine-88\n",
        filename="notes.txt",
        mime_type="text/plain",
    )
    first = make_agent(replica_a, db).run(
        "Read the attached notes file and tell me the owner's name.",
        session_id="s",
        files=[notes],
    )
    print(f"   replica A: {first.content}")

    second = make_agent(replica_b, db).run(
        "Read the notes file attached earlier once more and tell me the codename.",
        session_id="s",
    )
    print(
        f"   replica B: {second.content} (tools: {[t.tool_name for t in second.tools or []]})"
    )
    read_paths = [
        str((t.tool_args or {}).get("file_path", ""))
        for t in second.tools or []
        if t.tool_name == "Read"
    ]
    print(f"   replica B read: {read_paths}")
    assert all(str(replica_b) in p for p in read_paths), (
        "the file was restored under replica B's workspace"
    )
    print(
        f"   left under A: {files_under(replica_a)}, under B: {files_under(replica_b)}"
    )


def harness_output_is_removed_with_the_run_folder(
    workspace: Path, db: SqliteDb
) -> None:
    print("3. Claude writes a file beside the attachment:")
    agent = make_agent(workspace, db)
    run = agent.run(
        "Read the attached file, then use Write to save its text in upper case as upper.txt in the same folder as the "
        "attachment, and tell me the path you wrote.",
        session_id="write",
        files=[
            File(
                content=b"keep this short\n",
                filename="input.txt",
                mime_type="text/plain",
            )
        ],
    )
    print(f"   Claude: {str(run.content)[:120]}")
    print(f"   tools: {[t.tool_name for t in run.tools or []]}")
    print(f"   left under the workspace: {files_under(workspace)}")
    assert run.status == RunStatus.completed and not (workspace / ".agno").exists()


def symlinked_uploads_are_refused_once(workspace: Path, db: SqliteDb) -> None:
    print("4. .agno/uploads is a symlink to another directory, retries=2:")
    elsewhere = workspace.parent / "volume"
    elsewhere.mkdir()
    (workspace / ".agno").mkdir()
    (workspace / ".agno" / "uploads").symlink_to(elsewhere, target_is_directory=True)
    agent = make_agent(workspace, db, retries=2, delay_between_retries=0)
    run = agent.run(
        "Read the attached file.",
        session_id="symlink",
        files=[File(content=b"hi", filename="a.txt", mime_type="text/plain")],
    )
    metadata = run.metadata or {}
    print(f"   status: {run.status.value}, error: {run.content}")
    print(
        f"   retryable: {metadata.get('retryable')}, attempts: {metadata.get('attempts', 1)}, "
        f"error_type: {metadata.get('error_type')}"
    )
    print(f"   written into the volume: {sorted(p.name for p in elsewhere.iterdir())}")
    assert run.status == RunStatus.error, (
        "a symlinked uploads directory must be refused"
    )
    assert metadata.get("retryable") is False and "attempts" not in metadata, (
        "refused once, not retried"
    )


if __name__ == "__main__":
    failures = []
    with tempfile.TemporaryDirectory(prefix="agno-attachments-") as tmp:
        base = Path(tmp)
        db = SqliteDb(db_file=str(base / "runs.db"))
        for name, case in (
            ("one", lambda: failed_staging_leaves_nothing(base / "one")),
            ("two", lambda: restore_on_another_replica(base, db)),
            (
                "three",
                lambda: harness_output_is_removed_with_the_run_folder(
                    base / "three", db
                ),
            ),
            ("four", lambda: symlinked_uploads_are_refused_once(base / "four", db)),
        ):
            (base / name).mkdir(exist_ok=True)
            try:
                case()
            except AssertionError as error:
                # Each guarantee is checked on its own, so an older build shows which ones it lacks.
                failures.append(name)
                print(f"   FAIL: {error}")
    if failures:
        print(f"FAIL: guarantees not met in cases {failures}")
    else:
        print(
            "PASS: attachments are confined to the active workspace and cleaned up after each turn"
        )
