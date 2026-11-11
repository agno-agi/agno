"""
GitHub Events
=============

Receive a GitHub App's signed webhook deliveries for one repository and hand each
new issue or comment to a handler. The handler decides what an event becomes; here
it keeps what arrived and reads the issue back with the App's installation token.
It must record an event before returning, because GitHub does not retry a failed
delivery on its own.

Check locally, without GitHub (sends signed deliveries in process):
    .venvs/demo/bin/python cookbook/05_agent_os/32_github/basic.py --check

Serve for a GitHub App (create and install it first; see README.md):
    export GITHUB_WEBHOOK_SECRET=<the App's webhook secret>
    export GITHUB_APP_ID=<App ID>
    export GITHUB_APP_PRIVATE_KEY_PATH=<path to the App's .pem>
    export GITHUB_REPOSITORY=owner/name
    .venvs/demo/bin/python cookbook/05_agent_os/32_github/basic.py
    # In another terminal; the App's webhook URL is <ngrok URL>/github/events:
    ngrok http 7777
"""

import hashlib
import hmac
import json
import sys
from os import getenv
from typing import Any, Dict, List

import httpx
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS
from agno.os.interfaces.github import GitHub, GitHubEvent
from agno.utils.github_auth import GitHubAppCredentials

# ---------------------------------------------------------------------------
# Create the handler
# ---------------------------------------------------------------------------
received: List[GitHubEvent] = []
# Set when serving for a GitHub App; deliveries then name the installation whose token reads the issue.
credentials = GitHubAppCredentials() if getenv("GITHUB_APP_ID") else None


async def read_back(event: GitHubEvent) -> None:
    issue = event.issue or {}
    if credentials is None or event.installation_id is None or not issue:
        return
    try:
        token = await credentials.atoken(event.installation_id)
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"https://api.github.com/repos/{event.repository}/issues/{issue['number']}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                },
            )
        response.raise_for_status()
        print(
            f"Read #{issue['number']} with installation {event.installation_id}'s token: "
            f"{response.json()['state']}, {response.json()['comments']} comments"
        )
    except Exception as exc:
        # Reading back only demonstrates the App's token; the event itself is already recorded.
        print(f"Could not read #{issue['number']} with the App's token: {exc}")


async def record(event: GitHubEvent) -> Dict[str, Any]:
    received.append(event)
    issue = event.issue or {}
    print(
        f"{event.kind} on {event.repository} #{issue.get('number')} by {event.sender}: {issue.get('title')}"
    )
    await read_back(event)
    return {"received": len(received)}


# ---------------------------------------------------------------------------
# Create AgentOS
# ---------------------------------------------------------------------------
check = "--check" in sys.argv
secret = "local-check-secret" if check else getenv("GITHUB_WEBHOOK_SECRET")
repository = "agno-agi/agno" if check else getenv("GITHUB_REPOSITORY", "")

agent_os = AgentOS(
    id="github-events",
    description="Receive GitHub issue and comment events",
    db=SqliteDb(db_file="tmp/github_events.db"),
    interfaces=[
        GitHub(
            record,
            repositories=[repository],
            webhook_secret=secret,
            # A GitHub App's own comments are ignored as a bot's. With a personal token instead,
            # name the account that posts Agno's comments.
            ignore_logins=[getenv("GITHUB_BOT_LOGIN", "agno-bot")],
        )
    ],
    telemetry=False,
)
app = agent_os.get_app()


def run_check() -> None:
    from fastapi.testclient import TestClient

    client = TestClient(app)

    def deliver(
        event: str, payload: Dict[str, Any], key: str = "local-check-secret"
    ) -> Dict[str, Any]:
        body = json.dumps(payload).encode()
        signature = "sha256=" + hmac.new(key.encode(), body, hashlib.sha256).hexdigest()
        headers = {
            "X-GitHub-Event": event,
            "X-GitHub-Delivery": "check",
            "X-Hub-Signature-256": signature,
        }
        response = client.post("/github/events", content=body, headers=headers)
        return {"status_code": response.status_code, **response.json()}

    opened = {
        "action": "opened",
        "repository": {"full_name": "agno-agi/agno"},
        "sender": {"login": "alice", "type": "User"},
        "issue": {
            "number": 1,
            "title": "Export fails",
            "body": "Steps...",
            "user": {"login": "alice"},
        },
    }
    print(deliver("issues", opened))
    print(deliver("issues", {**opened, "repository": {"full_name": "someone/else"}}))
    print(
        deliver("issues", {**opened, "sender": {"login": "agno-bot", "type": "User"}})
    )
    print(deliver("issues", opened, key="wrong-secret"))
    assert len(received) == 1, received
    print(
        "Handled 1 of 4 deliveries: the other repository, Agno's own login and the bad signature were refused."
    )


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    if check:
        run_check()
    else:
        if credentials is None:
            print(
                "GITHUB_APP_ID is not set: events are received but not read back with an App token."
            )
        else:
            print(
                f"Reading each new issue back with GitHub App {credentials.app_id}'s installation token."
            )
        agent_os.serve(app="basic:app", port=7777, reload=False)
