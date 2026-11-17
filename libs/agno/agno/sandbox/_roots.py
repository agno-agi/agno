"""Checkpoint capture and restore of a computer's managed roots, run inside it as the agent's user.

A provider whose control process runs as root starts this as UID 1000, so root never
touches paths the agent controls; the host validates every archive that comes out.
"""

import json
import shutil
import sys
import tempfile
from pathlib import Path

from agno.sandbox.checkpoint import CheckpointArchive, CheckpointLimits


def _capture() -> None:
    """Write one validated checkpoint archive of the roots named on stdin to stdout."""
    job = json.loads(sys.stdin.buffer.read())
    roots = {name: Path(path) for name, path in job["roots"].items()}
    roots["native"].mkdir(mode=0o700, exist_ok=True)
    archive = CheckpointArchive(CheckpointLimits(**job["limits"]))
    with tempfile.TemporaryDirectory(prefix="agno-capture-") as directory:
        output = Path(directory) / "checkpoint.tar"
        archive.capture(roots, output, state=job["state"], exclude=job["exclude"])
        with output.open("rb") as stream:
            shutil.copyfileobj(stream, sys.stdout.buffer)
        sys.stdout.buffer.flush()


def _restore(arguments: str) -> None:
    """Restore the archive on stdin into the empty roots and write its manifest state to stdout."""
    job = json.loads(arguments)
    roots = {name: Path(path) for name, path in job["roots"].items()}
    archive = CheckpointArchive(CheckpointLimits(**job["limits"]))
    with tempfile.TemporaryDirectory(prefix="agno-restore-") as directory:
        source, staging = Path(directory) / "checkpoint", Path(directory) / "restored"
        with source.open("xb") as stream:
            shutil.copyfileobj(sys.stdin.buffer, stream)
        # Inside the computer, so absolute links name the paths they were captured with.
        state = archive.restore(source, staging, absolute_links=True)
        for name, target in roots.items():
            target.mkdir(mode=0o700, exist_ok=True)
            if target.is_symlink() or not target.is_dir() or any(target.iterdir()):
                raise SystemExit("Restore requires an empty, unused generation")
        for name, target in roots.items():
            # An archive may record a read-only root; its entries must still move out.
            (staging / name).chmod(0o700)
            for entry in (staging / name).iterdir():
                shutil.move(str(entry), str(target / entry.name))
            # The managed roots stay private whatever mode the archive recorded.
            target.chmod(0o700)
    sys.stdout.write(json.dumps(state))


def main() -> None:
    command = sys.argv[1:2]
    if command == ["capture"]:
        _capture()
    elif command == ["restore"] and len(sys.argv) == 3:
        _restore(sys.argv[2])
    else:
        sys.exit("usage: python -I -m agno.sandbox._roots capture | restore JOB")


if __name__ == "__main__":
    main()
