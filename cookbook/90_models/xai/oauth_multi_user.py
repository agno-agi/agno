"""
Xai SuperGrok Per-User Sign-In
==============================

Several people share one deployment and each spends their own SuperGrok
subscription. The token is stored under the user_id the run carries, and the
xAI model resolves that user's token per request, so two users on the same
agent never share a credential.

A user who has not signed in falls back to the deployment's own SuperGrok
session - the shared slot a script or an operator signs in to - which is what a
single-subscription deployment wants. Pass require_user_token=True to the model
to refuse that fallback and require every identified user to sign in first.

This script starts from an empty store, so there is no deployment session to
fall back to and the second user is asked to sign in instead. Sign in once
without a user_id, through oauth_device_login.py, to watch the fallback serve
somebody who never signed in.

user_id is passed directly here so the recipe runs without a server. In
production it arrives the same way from AgentOS, off the authenticated request.

Requires OPENAI_API_KEY (for the sign-in agent) and XAI_TOKEN_ENCRYPTION_KEY.
Generate an encryption key with:
python -c "from agno.utils.encryption import generate_encryption_key; print(generate_encryption_key())"
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.models.xai import xAIResponses
from agno.models.xai.oauth import XAITokenManager
from agno.tools.xai_auth import XAIAuth

# SqliteDb is for local development only; use PostgresDb in production.
# Per-user tokens need a database: one token file cannot hold one session each.
db = SqliteDb(db_file="tmp/xai_oauth.db")

token_manager = XAITokenManager(db=db)

# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------

# Not an xAI model: this agent runs the sign-in, so it cannot depend
# on the SuperGrok session it is about to create.
signin_agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[XAIAuth(token_manager=token_manager)],
    db=db,
    # The second turn refers back to the link handed out on the first
    add_history_to_context=True,
    markdown=True,
)

grok_agent = Agent(
    model=xAIResponses(token_manager=token_manager), db=db, markdown=True
)

# ---------------------------------------------------------------------------
# Run Agents
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- Alice signs in; the token is stored under her user_id ---
    signin_agent.print_response("Sign me in with SuperGrok", user_id="alice")

    input("Approve Alice's sign-in in your browser, then press Enter to continue...")

    signin_agent.print_response("Done, I approved it", user_id="alice")

    # --- Alice's question runs on Alice's subscription ---
    grok_agent.print_response("Share a 2 sentence horror story", user_id="alice")

    # --- Bob has not signed in: the deployment's shared session answers him,
    #     or he is told to sign in when the deployment has no session either ---
    grok_agent.print_response("Share a 2 sentence horror story", user_id="bob")

    # --- Bob signs in, and his requests carry his own subscription ---
    signin_agent.print_response("Sign me in with SuperGrok", user_id="bob")

    input("Approve Bob's sign-in in your browser, then press Enter to continue...")

    signin_agent.print_response("Done, I approved it", user_id="bob")
    grok_agent.print_response("Share a 2 sentence horror story", user_id="bob")
