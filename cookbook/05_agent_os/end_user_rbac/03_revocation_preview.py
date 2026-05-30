"""End-user RBAC: token revocation preview.

A preview of the Track B "User Governance" feature. Track B will productize
this with a persistent token store + audit log; this example shows the wiring
using an in-memory denylist so you can test the end-to-end flow today.

Every token issued by AgentOS.issue_token() carries a `jti` (JWT ID) claim. A
small piece of middleware reads that claim and rejects the request if the jti
is on the denylist.

What it does:
1. Boots an AgentOS with HS256 auth + an in-memory revocation middleware.
2. Mints a token for end-user "alice".
3. Hits /agents with the token -- 200.
4. Revokes alice's token.
5. Hits /agents again -- 401.

Run:
    export AGNO_JWT_SIGNING_KEY="..."
    .venvs/demo/bin/python cookbook/05_agent_os/end_user_rbac/03_revocation_preview.py
"""

import os
import threading
import time
from typing import Set

import httpx
import uvicorn
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.config import AuthorizationConfig
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

SIGNING_KEY = os.getenv("AGNO_JWT_SIGNING_KEY")
if not SIGNING_KEY:
    raise SystemExit("Set AGNO_JWT_SIGNING_KEY before running this example.")

REVOKED_JTIS: Set[str] = set()


class RevocationMiddleware(BaseHTTPMiddleware):
    """Reject requests whose JWT `jti` claim is on the denylist.

    Runs after JWTMiddleware has validated the token and stashed claims on
    request.state. Anything not authenticated (health, etc.) is passed through.
    """

    async def dispatch(self, request: Request, call_next):
        jti = getattr(request.state, "jti", None)
        if jti and jti in REVOKED_JTIS:
            return JSONResponse(status_code=401, content={"detail": "Token revoked"})
        return await call_next(request)


os.makedirs("tmp", exist_ok=True)
db = SqliteDb(db_file="tmp/end_user_rbac_revocation.db")

agent = Agent(
    id="chat-agent",
    name="Chat Agent",
    model=OpenAIResponses(id="gpt-5.4"),
    db=db,
)

agent_os = AgentOS(
    id="revocation-os",
    agents=[agent],
    authorization=True,
    authorization_config=AuthorizationConfig(
        verification_keys=[SIGNING_KEY],
        algorithm="HS256",
        verify_audience=True,
        audience="revocation-os",
    ),
)

app = agent_os.get_app()
app.add_middleware(RevocationMiddleware)


def _stash_jti_middleware(request: Request, call_next):
    """Copy the `jti` claim from the bearer token onto request.state.

    JWTMiddleware already validated the signature; we just need to surface the
    jti so RevocationMiddleware can check it. In Track B this will be built
    into JWTMiddleware itself.
    """
    import jwt as pyjwt

    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:]
        try:
            payload = pyjwt.decode(token, options={"verify_signature": False})
            request.state.jti = payload.get("jti")
        except Exception:
            pass
    return call_next(request)


app.middleware("http")(_stash_jti_middleware)


def run_server() -> None:
    uvicorn.run(app, host="127.0.0.1", port=7779, log_level="warning")


def main() -> None:
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    time.sleep(2)

    base = "http://127.0.0.1:7779"

    token = agent_os.issue_token(
        subject="alice",
        scopes=["agents:read"],
        ttl_seconds=3600,
    )

    import jwt as pyjwt

    decoded = pyjwt.decode(token, options={"verify_signature": False})
    jti = decoded["jti"]

    print("=" * 70)
    print("End-user RBAC: token revocation preview")
    print("=" * 70)
    print(f"\nIssued token for alice; jti={jti}")

    print("\n[1] First request (token valid):")
    r = httpx.get(
        f"{base}/agents", headers={"Authorization": f"Bearer {token}"}, timeout=10.0
    )
    print(f"  status={r.status_code}")

    print("\n[2] Revoking the token...")
    REVOKED_JTIS.add(jti)

    print("\n[3] Second request (token revoked):")
    r = httpx.get(
        f"{base}/agents", headers={"Authorization": f"Bearer {token}"}, timeout=10.0
    )
    print(f"  status={r.status_code}  body={r.text}")

    print("\n" + "=" * 70)
    print("In Track B this denylist becomes a persisted table with audit log.")
    print("=" * 70)


if __name__ == "__main__":
    main()
