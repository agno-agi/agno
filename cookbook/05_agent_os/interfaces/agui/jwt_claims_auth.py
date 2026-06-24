"""
JWT Claims Auth via AGUI forwardedProps
========================================

Demonstrates how to wire JWT-style identity and profile claims from the
frontend into the agent automatically using AGUI's claim-extraction config.

Pattern:
1. Your frontend (e.g. CopilotKit) verifies the user's JWT and decodes its
   claims into a flat dict (e.g. {"sub": ..., "email": ..., "name": ...}).
2. The frontend places those claims in the AGUI request's `forwardedProps`.
3. AGUI extracts them per your configuration and feeds them to the agent
   run as `user_id` and `dependencies`. Setting `dependencies_claims`
   automatically enables `add_dependencies_to_context=True`, so values
   appear in prompt templates.

Security note: JWT signature verification must happen on the frontend or in
upstream middleware. This interface trusts whatever forwardedProps contains.

Heads up: this example's `instructions` reference `{email}` and `{name}`. If
a request arrives without those keys in `forwardedProps`, the template
variables pass through as literal text (e.g. "User name: {name}") into the
LLM prompt - which is agno's documented behavior when dependencies are not
applied. Verify your wiring first with the curl example in the __main__
block before connecting from a UI client.
"""

from agno.agent.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.interfaces.agui import AGUI

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------

# The agent's instructions reference {email} and {name} via dependencies.
# AGUI will fill these in per-request from the decoded JWT claims.
chat_agent = Agent(
    name="ClaimsAwareAssistant",
    model=OpenAIResponses(id="gpt-5.5"),
    instructions=(
        "You are a helpful AI assistant. Greet the user by their first name when relevant. "
        "User email: {email}. User name: {name}."
    ),
    add_datetime_to_context=True,
    markdown=True,
)

# Configure AGUI to extract:
#   - "sub" claim (the JWT subject) -> user_id
#   - "email" and "name" claims    -> dependencies dict (auto-added to prompt context)
agent_os = AgentOS(
    agents=[chat_agent],
    interfaces=[
        AGUI(
            agent=chat_agent,
            user_id_claim="sub",
            dependencies_claims=["email", "name"],
        )
    ],
)
app = agent_os.get_app()


# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    """Run your AgentOS.

    Test with a curl that sets forwardedProps as if the frontend just decoded a JWT:

        curl -N -X POST http://localhost:9001/agui \\
          -H 'content-type: application/json' \\
          -d '{
            "threadId":"t1",
            "runId":"r1",
            "state":{},
            "messages":[{"id":"m1","role":"user","content":"Who am I?"}],
            "tools":[],
            "context":[],
            "forwardedProps":{
              "sub":"user-123",
              "email":"alice@example.com",
              "name":"Alice"
            }
          }'

    The agent's response will greet Alice by name and reference her email - those
    values were pulled from forwardedProps because of dependencies_claims.
    """
    agent_os.serve(app="jwt_claims_auth:app", reload=True, port=9001)
