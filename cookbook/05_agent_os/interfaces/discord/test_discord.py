"""
Discord Bot E2E Test
====================

Tests streaming, tool calls (task cards), reasoning, and conversation history.

Prerequisites:
    export DISCORD_PUBLIC_KEY="your-public-key"
    export DISCORD_APPLICATION_ID="your-app-id"
    export OPENAI_API_KEY="your-openai-key"

Run:
    python cookbook/05_agent_os/interfaces/discord/test_discord.py
"""

import json

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.os.app import AgentOS
from agno.os.interfaces.discord import Discord
from agno.tools.toolkit import Toolkit


class TestTools(Toolkit):
    """Simple tools for testing Discord task card rendering."""

    def __init__(self):
        super().__init__(name="test_tools")
        self.register(self.get_weather)
        self.register(self.calculate)

    def get_weather(self, city: str) -> str:
        """Get the current weather for a city.

        Args:
            city: The city name to get weather for.
        """
        return json.dumps(
            {"city": city, "temp": "22C", "condition": "Sunny", "humidity": "45%"}
        )

    def calculate(self, expression: str) -> str:
        """Evaluate a math expression.

        Args:
            expression: The math expression to evaluate.
        """
        try:
            result = eval(expression)  # noqa: S307
            return json.dumps({"expression": expression, "result": str(result)})
        except Exception as e:
            return json.dumps({"error": str(e)})


agent = Agent(
    name="Discord Bot",
    model=OpenAIResponses(id="gpt-4o-mini"),
    tools=[TestTools()],
    instructions=[
        "You are a helpful assistant on Discord.",
        "Use tools when the user asks about weather or math.",
    ],
    add_history_to_context=True,
    num_history_runs=3,
    add_datetime_to_context=True,
    markdown=True,
)

agent_os = AgentOS(
    agents=[agent],
    interfaces=[
        Discord(
            agent=agent,
            streaming=True,
        )
    ],
)
app = agent_os.get_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=7777)
