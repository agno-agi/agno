"""
Xai SuperGrok Device Login
==========================

Sign in with a SuperGrok subscription instead of an API key and run an agent
through xAIResponses. The device flow prints a URL and a code; approve the
sign-in in the browser and the token is stored encrypted and refreshed
automatically across restarts.

Requires XAI_TOKEN_ENCRYPTION_KEY. Generate a key with:
python -c "from agno.utils.encryption import generate_encryption_key; print(generate_encryption_key())"
"""

import time

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.xai import xAIResponses
from agno.models.xai.oauth import XAITokenManager

# SqliteDb is for local development only; use PostgresDb in production
db = SqliteDb(db_file="tmp/xai_oauth.db")
token_manager = XAITokenManager(db=db)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- Sign in with the device flow ---
    info = token_manager.start_device_login()
    print("Open this URL and approve the sign-in:")
    print(info.verification_uri_complete)
    print("Code: " + info.user_code)
    token_manager.poll_for_token(
        info.device_code, info.interval, time.time() + info.expires_in
    )
    print("Signed in. The token is stored encrypted and refreshes automatically.")

    # --- Model class syntax ---
    agent = Agent(model=xAIResponses(token_manager=token_manager), markdown=True)
    agent.print_response("Share a 2 sentence horror story")

    # --- String syntax ---
    agent = Agent(model="xai-responses:grok-4.3", markdown=True)
    # Attach the SuperGrok session to the model the string resolved to
    agent.model.token_manager = token_manager
    agent.print_response("Share a 2 sentence horror story")
