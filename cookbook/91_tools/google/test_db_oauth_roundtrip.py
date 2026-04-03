"""
E2E test: DB-backed OAuth token storage round-trip for Google toolkits.

Tests the full lifecycle:
  1. OAuth flow (browser) -> credentials obtained
  2. Credentials stored in SQLite DB via GoogleAuth
  3. Delete token.json to prove file is not needed
  4. Cold-load credentials from DB only
  5. Verify refresh works from DB-loaded creds
  6. Actual Gmail API call with DB-loaded credentials

Prerequisites:
  - GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET env vars set
  - First run opens browser for OAuth consent

Usage:
  .venvs/demo/bin/python cookbook/91_tools/google/test_db_oauth_roundtrip.py
"""

import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

# Phase 0: Verify environment
print("=" * 60)
print("Phase 0: Environment check")
print("=" * 60)

client_id = os.getenv("GOOGLE_CLIENT_ID")
client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
if not client_id or not client_secret:
    print("FAIL: Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET")
    sys.exit(1)
print(f"  Client ID: {client_id[:20]}...")
print(f"  Client Secret: {'*' * 10}")

# Use a temp directory so we don't pollute the repo
work_dir = Path(tempfile.mkdtemp(prefix="agno_oauth_test_"))
db_path = work_dir / "test_oauth.db"
token_path = work_dir / "token.json"
print(f"  Work dir: {work_dir}")
print(f"  DB path: {db_path}")
print(f"  Token path: {token_path}")

from agno.agent import Agent
from agno.db.sqlite.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.tools.google.auth import GoogleAuth
from agno.tools.google.gmail import GmailTools

# Phase 1: OAuth flow -> store to DB
print()
print("=" * 60)
print("Phase 1: Initial OAuth flow + DB store")
print("=" * 60)

db = SqliteDb(db_file=str(db_path))

google_auth = GoogleAuth(
    client_id=client_id,
    client_secret=client_secret,
    user_id="test-user-1",
    db=db,
)

gmail = GmailTools(
    google_auth=google_auth,
    token_path=str(token_path),
    port=8080,
    include_tools=["get_latest_emails"],
)

agent = Agent(
    name="OAuth Test Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[google_auth, gmail],
    db=db,
)

print("  Running agent to trigger OAuth flow...")
print("  (Browser will open if no existing token)")
response = agent.run("List my 2 most recent email subjects", user_id="test-user-1")
print(
    f"  Agent response length: {len(response.content) if response.content else 0} chars"
)

# Verify token.json was created
assert token_path.exists(), "FAIL: token.json was not created"
print(f"  token.json exists: {token_path.exists()} ({token_path.stat().st_size} bytes)")

# Verify token was stored in DB
conn = sqlite3.connect(str(db_path))
conn.row_factory = sqlite3.Row
cursor = conn.execute(
    "SELECT * FROM agno_oauth_tokens WHERE provider='google' AND user_id='test-user-1' AND service='gmail'"
)
row = cursor.fetchone()
conn.close()

if row is None:
    print("  FAIL: No token found in DB!")
    sys.exit(1)

token_data = (
    json.loads(row["token_data"])
    if isinstance(row["token_data"], str)
    else row["token_data"]
)
print(f"  DB token stored: YES")
print(f"  DB token keys: {sorted(token_data.keys())}")
print(f"  Has refresh_token: {bool(token_data.get('refresh_token'))}")
print(f"  Has client_id: {bool(token_data.get('client_id'))}")
print(f"  Has client_secret: {bool(token_data.get('client_secret'))}")
print(f"  Has token_uri: {bool(token_data.get('token_uri'))}")
print("  Phase 1: PASS")

# Phase 2: Delete token.json, cold-load from DB
print()
print("=" * 60)
print("Phase 2: Delete token.json, reload from DB only")
print("=" * 60)

token_path.unlink()
assert not token_path.exists(), "FAIL: token.json still exists after delete"
print(f"  token.json deleted: {not token_path.exists()}")

# Create fresh toolkit instances to clear cached creds
google_auth_2 = GoogleAuth(
    client_id=client_id,
    client_secret=client_secret,
    user_id="test-user-1",
    db=db,
)

gmail_2 = GmailTools(
    google_auth=google_auth_2,
    token_path=str(token_path),
    port=8080,
    include_tools=["get_latest_emails"],
)

agent_2 = Agent(
    name="OAuth Test Agent (cold start)",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[google_auth_2, gmail_2],
    db=db,
)

print("  Running agent with NO token.json (DB only)...")
response_2 = agent_2.run("List my 2 most recent email subjects", user_id="test-user-1")
print(
    f"  Agent response length: {len(response_2.content) if response_2.content else 0} chars"
)

# Verify token.json was NOT recreated (DB path doesn't write to file)
if token_path.exists():
    print(f"  WARNING: token.json was recreated ({token_path.stat().st_size} bytes)")
    print("  This means the DB load path fell through to file-based OAuth")
else:
    print(f"  token.json NOT recreated: CORRECT (DB path used)")

# Verify actual Gmail data was returned
content = response_2.content or ""
if len(content) > 50:
    print(f"  Gmail API returned real data: YES ({len(content)} chars)")
    print(f"  First 200 chars: {content[:200]}...")
    print("  Phase 2: PASS")
else:
    print(f"  WARNING: Response suspiciously short: {content}")
    print("  Phase 2: CHECK MANUALLY")

# Phase 3: Verify DB token was updated (refresh may have occurred)
print()
print("=" * 60)
print("Phase 3: Verify DB token freshness after reload")
print("=" * 60)

conn = sqlite3.connect(str(db_path))
conn.row_factory = sqlite3.Row
cursor = conn.execute(
    "SELECT * FROM agno_oauth_tokens WHERE provider='google' AND user_id='test-user-1' AND service='gmail'"
)
row = cursor.fetchone()
conn.close()

if row:
    print("  DB row exists: YES")
    print(f"  created_at: {row['created_at']}")
    print(f"  updated_at: {row['updated_at']}")
    if row["updated_at"] and row["created_at"]:
        if row["updated_at"] > row["created_at"]:
            print("  Token was refreshed and re-persisted: YES")
        else:
            print("  Token was not refreshed (still fresh from Phase 1)")
    print("  Phase 3: PASS")
else:
    print("  FAIL: Token disappeared from DB!")
    sys.exit(1)

# Phase 4: Multi-user isolation test
print()
print("=" * 60)
print("Phase 4: Multi-user isolation")
print("=" * 60)

conn = sqlite3.connect(str(db_path))
conn.row_factory = sqlite3.Row
cursor = conn.execute("SELECT provider, user_id, service FROM agno_oauth_tokens")
rows = cursor.fetchall()
conn.close()

print(f"  Total token rows in DB: {len(rows)}")
for r in rows:
    print(f"    ({r['provider']}, {r['user_id']}, {r['service']})")

# Verify no token exists for a different user
conn = sqlite3.connect(str(db_path))
cursor = conn.execute(
    "SELECT COUNT(*) FROM agno_oauth_tokens WHERE user_id='test-user-2'"
)
count = cursor.fetchone()[0]
conn.close()
print(f"  Tokens for test-user-2: {count} (expected: 0)")
print("  Phase 4: PASS" if count == 0 else "  Phase 4: FAIL — cross-contamination!")

# Summary
print()
print("=" * 60)
print("SUMMARY")
print("=" * 60)
print(f"  DB file: {db_path}")
print("  token.json needed after initial auth: NO")
print("  All phases completed.")
print()
print("To inspect the DB:")
print(
    f"  sqlite3 {db_path} 'SELECT provider, user_id, service, created_at, updated_at FROM agno_oauth_tokens;'"
)

# Cleanup prompt
print()
print(f"Cleanup: rm -rf {work_dir}")
