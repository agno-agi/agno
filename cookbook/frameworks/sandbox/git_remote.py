"""Disposable, unauthenticated Git remote on the private test network only."""

import subprocess
from pathlib import Path

if __name__ == "__main__":
    root = Path("/tmp/git")
    root.mkdir(exist_ok=True)
    subprocess.run(
        ["git", "init", "--bare", "--initial-branch=main", str(root / "workspace.git")],
        check=True,
    )
    seed = root / "seed"
    subprocess.run(["git", "init", "--initial-branch=main", str(seed)], check=True)
    (seed / "README.md").write_text("Sandbox recovery fixture\n")
    for args in (
        ["add", "."],
        [
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@localhost",
            "commit",
            "-m",
            "Initial",
        ],
        ["push", str(root / "workspace.git"), "main"],
    ):
        subprocess.run(["git", "-C", str(seed), *args], check=True)
    subprocess.run(
        [
            "git",
            "daemon",
            "--reuseaddr",
            "--export-all",
            "--enable=receive-pack",
            "--base-path=" + str(root),
            str(root),
        ],
        check=True,
    )
