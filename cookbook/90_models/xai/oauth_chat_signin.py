"""
Xai SuperGrok Chat Sign-In
==========================

Sign in with a SuperGrok subscription from inside the conversation. The agent
carries the XAIAuth toolkit: the first turn hands the user an approval link,
and a later turn finishes the sign-in once the user says they approved it.
Use this shape for chatbots and web UIs, where the terminal device flow in
oauth_device_login.py will not work.

The toolkit and the model share one token manager, so the credential the tool
stores is the credential the model spends on the next turn.

Requires XAI_TOKEN_ENCRYPTION_KEY. Generate a key with:
python -c "from agno.utils.encryption import generate_encryption_key; print(generate_encryption_key())"
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.xai import xAIResponses
from agno.models.xai.oauth import XAITokenManager
from agno.tools.xai_auth import XAIAuth

# SqliteDb is for local development only; use PostgresDb in production
db = SqliteDb(db_file="tmp/xai_oauth.db")

# One manager for both roles: the toolkit signs in, the model spends the session
token_manager = XAITokenManager(db=db)

agent = Agent(
    model=xAIResponses(token_manager=token_manager),
    tools=[XAIAuth(token_manager=token_manager)],
    db=db,
    # The second turn refers back to the link handed out on the first
    add_history_to_context=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- Turn 1: the agent hands back the approval link and the code ---
    agent.print_response("Sign me in with SuperGrok")

    input("Approve the sign-in in your browser, then press Enter to continue...")

    # --- Turn 2: the agent finishes the sign-in and answers through the session ---
    agent.print_response("Done, I approved it. Now share a 2 sentence horror story")

    # --- String syntax ---
    agent = Agent(model="xai-responses:grok-4.3", markdown=True)
    # Attach the SuperGrok session to the model the string resolved to
    agent.model.token_manager = token_manager
    agent.print_response("Share a 2 sentence horror story")
