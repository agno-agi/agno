"""Build only public package sources into a runtime image; never send the working tree."""

import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", default="agno-sandbox:local")
    parser.add_argument(
        "--platform", help="For example linux/arm64, which AgentCore requires"
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    with tempfile.TemporaryDirectory(prefix="agno-runtime-build-") as directory:
        context = Path(directory)
        shutil.copytree(
            root / "libs/agno/agno",
            context / "agno",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        for filename in ("pyproject.toml", "LICENSE"):
            shutil.copyfile(root / "libs/agno" / filename, context / filename)
        shutil.copyfile(root / "README.md", context / "README.md")
        shutil.copyfile(Path(__file__).with_name("Dockerfile"), context / "Dockerfile")
        # --load puts the result in the daemon's image store: a docker-container builder
        # otherwise keeps it in the build cache and exits 0 with no image to run.
        command = ["docker", "build", "--progress=plain", "--load", "--tag", args.tag]
        if args.platform:
            command += ["--platform", args.platform]
        subprocess.run([*command, str(context)], check=True)
    inspected = subprocess.run(
        ["docker", "image", "inspect", "--format", "{{.Id}}", args.tag],
        capture_output=True,
        text=True,
    )
    if inspected.returncode != 0:
        raise SystemExit(
            f"docker build exited 0 but {args.tag} is not in the image store; "
            "use a builder that can load images (docker buildx use default) and rebuild"
        )
    print(f"Built {args.tag} ({inspected.stdout.strip()})")


if __name__ == "__main__":
    main()
