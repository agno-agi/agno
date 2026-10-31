"""Check the regular-user example's HTTP permissions without any model calls.

Set JWT_VERIFICATION_KEY to a local development signing key of at least 32
characters. No OPENAI_API_KEY is needed. Uses an in-process client, so do not
start a separate server. Tokens are generated for these checks and never printed.
The companion example uses tmp/manager-access.db, the same as when it is served.

These checks cover HTTP authentication, discovery, session access and denied
publishing. Tool-level and delegated permissions are covered by the unit tests.

Run:
    .venvs/demo/bin/python cookbook/05_agent_os/29_manager/check_manager_permissions.py
"""

from os import environ

from agno.os import create_dev_token
from fastapi.testclient import TestClient
from manager_user_access import app


def main() -> None:
    secret = environ["JWT_VERIFICATION_KEY"]

    def token_headers(user: str, audience: str = "manager-access-demo") -> dict:
        token = create_dev_token(
            user,
            secret=secret,
            audience=audience,
            # Managed roles must ignore this claim: Alice is still not an admin.
            scopes=["agent_os:admin"],
        )
        return {"Authorization": f"Bearer {token}"}

    with TestClient(app) as client:
        alice = token_headers("alice")
        manager_path = "/teams/os-manager-internal"
        checks = [
            (
                "Alice can discover OS Manager",
                client.get(manager_path, headers=alice),
                200,
            ),
            (
                "Alice can discover math-helper",
                client.get("/agents/math-helper", headers=alice),
                200,
            ),
            (
                "Alice can list her sessions",
                client.get("/sessions", headers=alice),
                200,
            ),
            (
                "An unassigned user cannot discover OS Manager",
                client.get(manager_path, headers=token_headers("bob")),
                403,
            ),
            ("Anonymous access is refused", client.get(manager_path), 401),
            (
                "Wrong audience is refused",
                client.get(manager_path, headers=token_headers("alice", "another-os")),
                401,
            ),
            (
                "An admin token claim cannot grant Alice publishing access",
                client.post(
                    "/components",
                    headers=alice,
                    json={
                        "name": "Must not publish",
                        "component_type": "agent",
                        "config": {},
                    },
                ),
                403,
            ),
        ]
        for label, response, expected in checks:
            if response.status_code != expected:
                raise AssertionError(
                    f"{label}: expected HTTP {expected}, got {response.status_code}"
                )
            print(f"PASS: {label} (HTTP {expected})")
    print("All seven permission checks passed. No model calls were made.")


if __name__ == "__main__":
    main()
