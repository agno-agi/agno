"""
Xai SuperGrok Chat Sign-In
==========================

Sign in with a SuperGrok subscription from inside the conversation. Two agents
share one token manager: a sign-in agent carries the XAIAuth toolkit and walks
the user through the approval link, and a Grok agent spends the subscription
once the sign-in lands. Use this shape for chatbots and web UIs, where the
terminal device flow in oauth_device_login.py will not work.

The split is not stylistic. An agent cannot sign in to the model it is running
on: reaching the sign-in tool takes an inference call, and that call is the one
with no credential yet.

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

# SqliteDb is for local development only; use PostgresDb in production
db = SqliteDb(db_file="tmp/xai_oauth.db")

# One manager for both roles: the toolkit signs in, the Grok agent spends the session
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

grok_agent = Agent(model=xAIResponses(token_manager=token_manager), markdown=True)

# ---------------------------------------------------------------------------
# Run Agents
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- Turn 1: the sign-in agent hands back the approval link and the code ---
    signin_agent.print_response("Sign me in with SuperGrok")

    input("Approve the sign-in in your browser, then press Enter to continue...")

    # --- Turn 2: the sign-in agent finishes the sign-in and stores the token ---
    signin_agent.print_response("Done, I approved it")

    # --- Turn 3: the Grok agent answers on the subscription just signed into ---
    grok_agent.print_response("Share a 2 sentence horror story")

    # --- String syntax ---
    grok_agent = Agent(model="xai-responses:grok-4.3", markdown=True)
    # Attach the SuperGrok session to the model the string resolved to
    grok_agent.model.token_manager = token_manager
    grok_agent.print_response("Share a 2 sentence horror story")
