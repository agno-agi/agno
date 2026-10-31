"""Attachment staging failures must not leak files or trust historical write paths."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from agno.agents import _media


def attachment(name, data=b"payload"):
    return SimpleNamespace(filename=name, content=data)


def fail_open(monkeypatch, name="second.txt"):
    original = Path.open

    def opening(path, *args, **kwargs):
        if path.name == name and args and args[0] == "xb":
            raise OSError("injected staging failure")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", opening)


def test_staging_rolls_back_only_its_new_files(tmp_path, monkeypatch):
    root = _media.uploads_root(tmp_path, "run")
    root.mkdir(parents=True)
    (root / "first.txt").write_bytes(b"user edit")
    fail_open(monkeypatch)
    with pytest.raises(OSError, match="injected"):
        _media.stage_media(tmp_path, "run", {"files": [attachment("first.txt"), attachment("second.txt")]})
    assert list(root.iterdir()) == [root / "first.txt"]
    assert (root / "first.txt").read_bytes() == b"user edit"


def test_partial_write_is_removed(tmp_path, monkeypatch):
    original = Path.open

    class FailingWrite:
        def __init__(self, file):
            self.file = file

        def __enter__(self):
            return self

        def write(self, data):
            self.file.write(data[:1])
            raise OSError("disk full")

        def __exit__(self, *args):
            self.file.close()

    def opening(path, *args, **kwargs):
        file = original(path, *args, **kwargs)
        return FailingWrite(file) if args and args[0] == "xb" else file

    monkeypatch.setattr(Path, "open", opening)
    with pytest.raises(OSError, match="disk full"):
        _media.stage_media(tmp_path, "run", {"files": [attachment("first.txt")]})
    assert not (tmp_path / ".agno").exists()


@pytest.mark.parametrize("run_id", ["../escape", "/outside", "..", ".", "", "a/b", "a\\b", "C:escape"])
def test_run_ids_cannot_escape_the_upload_directory(tmp_path, run_id):
    with pytest.raises(ValueError, match="run_id"):
        _media.stage_media(tmp_path, run_id, {"files": [attachment("x")]})
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("level", [".agno", ".agno/uploads", ".agno/uploads/run"])
def test_directory_symlinks_are_rejected(tmp_path, level):
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    outside.mkdir()
    link = workspace / level
    link.parent.mkdir(parents=True)
    link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="symlinks"):
        _media.stage_media(workspace, "run", {"files": [attachment("x")]})
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize("reuse", [False, True])
def test_leaf_symlinks_are_not_followed_or_reused(tmp_path, reuse):
    outside = tmp_path / "secret"
    outside.write_bytes(b"private")
    root = _media.uploads_root(tmp_path, "run")
    root.mkdir(parents=True)
    (root / "x").symlink_to(outside)
    with pytest.raises(ValueError, match="symlinks"):
        _media.stage_media(tmp_path, "run", {"files": [attachment("x")]}, reuse_existing=reuse)
    assert outside.read_bytes() == b"private"


def test_writable_historical_root_is_only_a_locator(tmp_path, monkeypatch):
    outside = tmp_path / "previous-replica"
    outside.mkdir()
    session = SimpleNamespace(session_data={"uploads_root": str(outside)})
    monkeypatch.setattr(_media, "prior_attachments", lambda *a: {"old": {"files": [attachment("x")]}})
    workspace = tmp_path / "current"
    folders, note = _media.stage_prior_media(workspace, session)
    assert list(outside.iterdir()) == []
    assert (workspace / ".agno/uploads/old/x").read_bytes() == b"payload"
    assert folders == [workspace / ".agno/uploads/old"]
    assert "have moved" in note


def test_restore_failure_rolls_back_new_files_across_runs(tmp_path, monkeypatch):
    existing = _media.uploads_root(tmp_path, "first")
    existing.mkdir(parents=True)
    (existing / "retained.txt").write_bytes(b"keep")
    monkeypatch.setattr(
        _media,
        "prior_attachments",
        lambda *a: {
            "first": {"files": [attachment("first.txt")]},
            "second": {"files": [attachment("second.txt")]},
        },
    )
    fail_open(monkeypatch)
    with pytest.raises(OSError, match="injected"):
        _media.stage_prior_media(tmp_path, None)
    assert list(existing.iterdir()) == [existing / "retained.txt"]


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", ["claude", "codex", "codex_stream"])
@pytest.mark.parametrize("keep", [False, True])
async def test_prior_restore_failure_cleans_current_input_before_sdk(tmp_path, monkeypatch, harness, keep):
    if harness == "claude":
        from agno.agents.claude import ClaudeAgent
        from agno.agents.claude import agent as module

        agent = ClaudeAgent(id="test", cwd=tmp_path, keep_uploads=keep)
    else:
        from agno.agents.codex import CodexAgent
        from agno.agents.codex import agent as module

        agent = CodexAgent(id="test", cwd=str(tmp_path), keep_uploads=keep)

    def fail(*args, **kwargs):
        raise OSError("prior restore failed")

    monkeypatch.setattr(module, "stage_prior_media", fail)
    kwargs = dict(run_id="current", media={"files": [attachment("current.txt")]})
    with pytest.raises(OSError, match="prior restore failed"):
        if harness == "claude":
            async for _ in agent._aquery("input", None, streaming=False, **kwargs):
                pytest.fail("SDK was reached")
        elif harness == "codex_stream":
            async for _ in agent._arun_adapter_stream("input", **kwargs):
                pytest.fail("SDK was reached")
        else:
            await agent._arun_adapter("input", **kwargs)
    assert not (tmp_path / ".agno").exists()


def test_cleanup_preserves_preexisting_inputs_and_duplicate_names(tmp_path):
    root = _media.uploads_root(tmp_path, "run")
    root.mkdir(parents=True)
    (root / "x.txt").write_bytes(b"retained")
    staged = _media.stage_media(tmp_path, "run", {"files": [attachment("x.txt"), attachment("x.txt")]})
    assert [item.name for item in staged] == ["x-2.txt", "x-2-3.txt"]
    _media.cleanup_staged_media(staged)
    assert list(root.iterdir()) == [root / "x.txt"]
    assert (root / "x.txt").read_bytes() == b"retained"


def test_a_run_folder_created_by_the_turn_goes_whole_a_preexisting_one_keeps_its_files(tmp_path):
    """The harness may write next to the inputs. A folder this staging created holds only this
    run's work and is removed whole; a folder that existed before loses only the staged inputs."""
    staged = _media.stage_media(tmp_path, "fresh", {"files": [attachment("in.txt")]})
    (tmp_path / ".agno/uploads/fresh/harness-output.txt").write_bytes(b"made by the harness")
    _media.cleanup_run_media(tmp_path, "fresh", staged, created_root=True)
    assert not (tmp_path / ".agno").exists()

    root = _media.uploads_root(tmp_path, "kept")
    root.mkdir(parents=True)
    (root / "user.txt").write_bytes(b"retained")
    staged = _media.stage_media(tmp_path, "kept", {"files": [attachment("in.txt")]})
    (root / "harness-output.txt").write_bytes(b"made by the harness")
    _media.cleanup_run_media(tmp_path, "kept", staged, created_root=False)
    assert sorted(p.name for p in root.iterdir()) == ["harness-output.txt", "user.txt"]


@pytest.mark.asyncio
@pytest.mark.parametrize("harness", ["claude", "codex"])
async def test_wrappers_remove_the_run_folder_they_created_with_the_harness_output(tmp_path, monkeypatch, harness):
    if harness == "claude":
        from agno.agents.claude import ClaudeAgent

        agent = ClaudeAgent(id="test", cwd=tmp_path)

        async def sdk(input, history, *, streaming, **kwargs):
            (tmp_path / ".agno/uploads/current/harness-output.txt").write_bytes(b"x")
            yield "message"

        monkeypatch.setattr(agent, "_aquery_sdk", sdk)
        async for _ in agent._aquery(
            "input", None, streaming=False, run_id="current", media={"files": [attachment("in.txt")]}
        ):
            pass
    else:
        from agno.agents.codex import CodexAgent

        agent = CodexAgent(id="test", cwd=str(tmp_path))

        async def sdk(input, *, history=None, **kwargs):
            (tmp_path / ".agno/uploads/current/harness-output.txt").write_bytes(b"x")
            return "done"

        monkeypatch.setattr(agent, "_arun_adapter_sdk", sdk)
        await agent._arun_adapter("input", run_id="current", media={"files": [attachment("in.txt")]})
    assert not (tmp_path / ".agno").exists()


def test_staging_errors_are_input_errors_and_never_retried(tmp_path):
    """A symlinked uploads directory fails every attempt the same way: one attempt, not retryable,
    reported as an input check error rather than a generic ValueError."""
    from agno.agents.claude import ClaudeAgent
    from agno.exceptions import InputCheckError, MediaStagingError
    from agno.run.base import RunStatus

    outside = tmp_path / "volume"
    outside.mkdir()
    workspace = tmp_path / "workspace"
    (workspace / ".agno").mkdir(parents=True)
    (workspace / ".agno/uploads").symlink_to(outside, target_is_directory=True)
    agent = ClaudeAgent(id="test", cwd=workspace, retries=2, delay_between_retries=0)
    from agno.media import File

    run = agent.run("read it", files=[File(content=b"hi", filename="a.txt", mime_type="text/plain")])
    assert run.status == RunStatus.error
    assert "symlinks" in str(run.content)
    assert run.metadata["retryable"] is False and "attempts" not in run.metadata
    assert run.metadata["error_type"] == "input_check_error"
    assert issubclass(MediaStagingError, InputCheckError) and issubclass(MediaStagingError, ValueError)
    assert list(outside.iterdir()) == []


def test_long_names_keep_their_extension_when_truncated():
    name = _media._safe_name("a" * 300 + ".txt")
    assert len(name) == 120 and name.endswith(".txt")
    assert _media._safe_name("short.txt") == "short.txt"
    assert len(_media._safe_name("a" * 300)) == 120


def test_inline_blocks_follow_the_bytes_not_the_label(tmp_path):
    """A file labelled PDF that holds HTML stays on disk; an untyped PNG goes inline under its old name."""
    from agno.agents._media import inline_blocks, media_prompt_block, stage_media
    from agno.media import File, Image

    png = b"\x89PNG\r\n\x1a\n" + bytes(range(64))
    media = {
        "images": [Image(content=png)],
        "files": [File(content=b"<html>not a pdf</html>", filename="memo.pdf", mime_type="application/pdf")],
    }
    staged = stage_media(tmp_path, "run-1", media)
    blocks = inline_blocks(staged)

    assert staged[0].name == "image-1.bin", "the disk name is what earlier releases chose"
    assert staged[0].mime_type == "image/png" and staged[0].inline
    assert [b["type"] for b in blocks] == ["image"] and blocks[0]["source"]["media_type"] == "image/png"
    assert not staged[1].inline, "mislabelled document is left for the file tools"
    prompt = media_prompt_block(staged)
    image_line, pdf_line = [line for line in prompt.splitlines() if line.startswith("- ")]
    assert "do not read it" in image_line and "read it with the file tools" in pdf_line
    assert "Read them" not in prompt
