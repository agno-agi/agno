"""Download a completed workspace artifact without starting sandbox compute."""

import argparse
import os
from pathlib import Path
from urllib.parse import quote

import httpx


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", required=True)
    parser.add_argument("--path", default="fixture-effects.txt")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    headers = {}
    if os.environ.get("SANDBOX_BEARER_TOKEN"):
        headers["Authorization"] = "Bearer " + os.environ["SANDBOX_BEARER_TOKEN"]
    endpoint = "/agents/coder/sessions/" + quote(args.session, safe="") + "/sandbox"
    with httpx.Client(
        base_url=os.environ.get("SANDBOX_API_URL", "http://localhost:7777"),
        headers=headers,
        timeout=60,
    ) as client:
        status = client.get(endpoint)
        status.raise_for_status()
        print(status.json())
        listing = client.get(endpoint + "/artifacts")
        listing.raise_for_status()
        print(listing.json())
        artifact = client.get(endpoint + "/artifact", params={"path": args.path})
        artifact.raise_for_status()
        # Exclusive creation protects an existing local file from replacement.
        with args.output.open("xb") as output:
            output.write(artifact.content)
        print("Downloaded completed checkpoint:", artifact.headers["x-agno-checkpoint"])


if __name__ == "__main__":
    main()
