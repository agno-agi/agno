"""
Basic
=====

Expose an Agno agent behind the Anthropic Messages API.

This boots an AgentOS app whose `/v1/messages`, `/v1/messages/count_tokens`, and
`/v1/models` endpoints speak the Anthropic Messages API, so the Anthropic Python SDK
(or Claude Code with `ANTHROPIC_BASE_URL=http://localhost:9001`) can use the Agno
agent as the upstream model.

Try it with the Anthropic SDK:

    import anthropic
    client = anthropic.Anthropic(api_key="dev", base_url="http://localhost:9001")
    msg = client.messages.create(
        model="claude-agno-assistant",
        max_tokens=256,
        messages=[{"role": "user", "content": "Tell me a fact about Saturn."}],
    )
    print(msg.content[0].text)
"""

from agno.agent.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.interfaces.anthropic import AnthropicInterface

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------

db = SqliteDb(db_file="tmp/anthropic_basic.db")

assistant = Agent(
    name="Assistant",
    model=OpenAIResponses(id="gpt-5.4"),
    instructions="You are a helpful AI assistant. Keep answers concise.",
    add_datetime_to_context=True,
    markdown=True,
    db=db,
)

# Set AGNO_ANTHROPIC_INTERFACE_API_KEY in your env to require a static API key on
# every request. Omit it during development to leave the interface open.
agent_os = AgentOS(
    agents=[assistant],
    db=db,
    interfaces=[AnthropicInterface(agent=assistant)],
)
app = agent_os.get_app()


# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    """Run your AgentOS.

    You can see the configuration and available apps at:
    http://localhost:9001/config
    """
    agent_os.serve(app="basic:app", reload=True, port=9001)
