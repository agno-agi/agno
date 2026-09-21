"""Start the protected page sync on AgentOS and print its progress as it arrives.

Run `public_pages.py serve` first; see README.md. Needs PAGE_DEMO_SYNC_TOKEN, the same
trusted token the server was started with. The page source is the server's
PAGE_DEMO_INDEX_URL; this client cannot choose one.
"""

import argparse
import asyncio
import json
import sys
from os import getenv

from agno.client import AgentOSClient
from agno.run.workflow import (
    StepProgressEvent,
    WorkflowCancelledEvent,
    WorkflowCompletedEvent,
    WorkflowErrorEvent,
)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reindex", action="store_true", help="Re-embed unchanged pages too"
    )
    args = parser.parse_args()
    token = getenv("PAGE_DEMO_SYNC_TOKEN")
    if not token:
        print(
            "Set PAGE_DEMO_SYNC_TOKEN to the token the server was started with.",
            file=sys.stderr,
        )
        return 2

    # A page sync may run for its whole 65 minute budget; the client default is 60 seconds.
    client = AgentOSClient(
        base_url=getenv("PAGE_DEMO_SERVER_URL", "http://127.0.0.1:7777"), timeout=3900
    )
    request = json.dumps({"reason": "page_sync_progress.py", "reindex": args.reindex})
    progress, report = 0, None
    async for event in client.run_workflow_stream(
        workflow_id="sync-docs",
        message=request,
        headers={"Authorization": f"Bearer {token}"},
    ):
        if isinstance(event, StepProgressEvent) and event.content:
            progress += 1
            print(event.content)
        elif isinstance(event, WorkflowErrorEvent):
            print(f"Sync failed: {event.error}", file=sys.stderr)
            return 1
        elif isinstance(event, WorkflowCancelledEvent):
            print(f"Sync was cancelled: {event.reason}", file=sys.stderr)
            return 1
        elif isinstance(event, WorkflowCompletedEvent):
            report = event.content

    if not isinstance(report, dict):
        print("The sync ended without a report.", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2))
    if not progress:
        print("The sync reported no page progress.", file=sys.stderr)
        return 1
    return 1 if report.get("status") == "partial" else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
