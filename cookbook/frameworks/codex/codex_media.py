"""
Attach images and files to a CodexAgent run
===========================================
Images go to Codex as native image inputs on the turn, so the model sees
them directly. Files are written under cwd/.agno/uploads/<run_id>/ and named
in the prompt, and Codex reads them with its shell. The folder is removed
when the run ends unless keep_uploads=True. Audio and video are rejected
before the run starts.

The same works through AgentOS: attach files in the UI or post them as
multipart form fields, exactly like a native agent.

Requirements:
    pip install openai-codex

Usage:
    .venvs/demo/bin/python cookbook/frameworks/codex/codex_media.py
"""

import struct
import tempfile
import zlib
from pathlib import Path

from agno.agents.codex import CodexAgent
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
    with tempfile.TemporaryDirectory(prefix="agno-codex-media-") as workdir:
        agent = CodexAgent(
            id="media-demo",
            model="gpt-5.6-luna",
            sandbox="read-only",
            db=SqliteDb(db_file=f"{workdir}/runs.db"),
            cwd=workdir,
        )

        image = Image(content=solid_png(64, 64, (30, 60, 220)), format="png")
        data = File(
            content=b"region,amount\nnorth,120\nsouth,80\n",
            filename="sales.csv",
            mime_type="text/csv",
        )
        run = agent.run(
            "An image and a CSV file are attached. What colour is the image, and what is the total of the amount "
            "column in the CSV? Answer in one line.",
            images=[image],
            files=[data],
            session_id="media",
        )
        assert run.status == RunStatus.completed, run.content
        print(f"Answer: {run.content}")
        assert "200" in (run.content or "")

        print(
            f"Recorded attachments: {[f.filename for f in run.input.files]} and {len(run.input.images)} image"
        )
        assert not (Path(workdir) / ".agno" / "uploads").exists()


if __name__ == "__main__":
    main()
