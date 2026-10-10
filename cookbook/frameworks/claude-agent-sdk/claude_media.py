"""
Attach images and files to a ClaudeAgent run
============================================
Claude Code reads files itself, so attachments reach it the way they reach
a person at a terminal: Agno writes each image or file under
cwd/.agno/uploads/<run_id>/ and names the paths in the prompt. Claude opens
them with its Read tool, which handles images and PDFs. The folder is
removed when the run ends unless keep_uploads=True, and re-created from the
recorded run before any later turn of the session, so Claude can open the
same files again on whichever replica runs that turn. Audio and video are
rejected before the run starts, since Claude Code has no way to use them.

The same works through AgentOS: attach files in the UI or post them as
multipart form fields, exactly like a native agent.

Usage:
    .venvs/demo/bin/python cookbook/frameworks/claude-agent-sdk/claude_media.py
"""

import struct
import tempfile
import zlib
from pathlib import Path

from agno.agents.claude import ClaudeAgent
from agno.db.sqlite import SqliteDb
from agno.media import File, Image
from agno.run.base import RunStatus


def solid_png(width: int, height: int, rgb: tuple) -> bytes:
    """A small PNG filled with one colour."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    row = b"\x00" + bytes(rgb) * width
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(row * height))
        + chunk(b"IEND", b"")
    )


def main():
    with tempfile.TemporaryDirectory(prefix="agno-media-") as workdir:
        agent = ClaudeAgent(
            id="media-demo",
            model="claude-sonnet-4-6",
            db=SqliteDb(db_file=str(Path(workdir) / "runs.db")),
            cwd=workdir,
            allowed_tools=["Read"],
            permission_mode="bypassPermissions",
            max_turns=4,
            max_budget_usd=0.5,
        )

        image = Image(content=solid_png(64, 64, (220, 40, 40)), format="png")
        notes = File(
            content=b"Release checklist\n- codename: tangerine-walrus-88\n- owner: platform team\n",
            filename="release-notes.txt",
            mime_type="text/plain",
        )
        run = agent.run(
            "Two files are attached. What colour is the image, and what is the release codename in the notes? "
            "Answer in one line.",
            images=[image],
            files=[notes],
            session_id="media",
        )
        assert run.status == RunStatus.completed, run.content
        print(f"Answer: {run.content}")
        assert "tangerine-walrus-88" in (run.content or "")

        # The run records what was attached, and the staged files are gone after the run.
        print(
            f"Recorded attachments: {[f.filename for f in run.input.files]} and {len(run.input.images)} image"
        )
        assert not (Path(workdir) / ".agno" / "uploads").exists()

        # 2. A later turn can open the same files again: they are re-staged from the recorded
        #    run before each turn, at the paths Claude already knows, on whichever replica runs
        #    it. A second agent instance with its own working directory stands in for another
        #    replica; when the path differs, the prompt tells Claude where the files are now.
        other_workdir = Path(workdir) / "replica-b"
        other_workdir.mkdir()
        other = ClaudeAgent(
            id="media-demo",
            model="claude-sonnet-4-6",
            db=SqliteDb(db_file=str(Path(workdir) / "runs.db")),
            cwd=str(other_workdir),
            allowed_tools=["Read"],
            permission_mode="bypassPermissions",
            max_turns=4,
            max_budget_usd=0.5,
        )
        later = other.run(
            "Read the release notes file again with the Read tool and quote the owner line exactly.",
            session_id="media",
        )
        assert later.status == RunStatus.completed, later.content
        print(f"Later turn on another replica, file re-read: {later.content}")
        assert "platform team" in (later.content or "")
        assert not (other_workdir / ".agno" / "uploads").exists()


if __name__ == "__main__":
    main()
