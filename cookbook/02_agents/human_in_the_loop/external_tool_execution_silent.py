"""External Tool Execution: Silent Mode

This example demonstrates external_execution_silent=True, which suppresses
the verbose "I have tools to execute..." messages when tools are paused.

- Default (external_execution_silent=False): Prints paused messages
- Silent (external_execution_silent=True): No verbose messages

Run: pip install openai agno
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.tools import tool
from agno.utils import pprint


@tool(external_execution=True, external_execution_silent=True)
def get_weather(city: str) -> str:
    """Get the current weather for a city.

    Args:
        city: The city name to get weather for

    Returns:
        The weather information for the city
    """
    # Simulated external API call
    return f"Weather in {city}: Sunny, 72F"


agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[get_weather],
    markdown=True,
    db=SqliteDb(session_table="test_session", db_file="tmp/example.db"),
)

# Note: With external_execution_silent=True, you won't see
# "I have tools to execute..." when the agent pauses

run_response = agent.run("What's the weather in San Francisco?")

if run_response.is_paused:
    print("Agent is paused for external execution")
    print(f"Tools requiring execution: {len(run_response.active_requirements)}")

    # This is where you see the difference:
    # - external_execution_silent=False: shows "I have tools to execute..."
    # - external_execution_silent=True: content is empty (no verbose message)
    print(f"Paused content: '{run_response.content}'")

    for requirement in run_response.active_requirements:
        if requirement.needs_external_execution:
            tool_name = requirement.tool_execution.tool_name
            tool_args = requirement.tool_execution.tool_args or {}

            print(f"Executing: {tool_name}({tool_args})")

            if tool_name == get_weather.name and "city" in tool_args:
                result = get_weather.entrypoint(**tool_args)
                requirement.set_external_execution_result(result)
            else:
                # Handle missing arguments gracefully
                requirement.set_external_execution_result(
                    "Unable to execute: missing arguments"
                )

    run_response = agent.continue_run(
        run_id=run_response.run_id,
        requirements=run_response.requirements,
    )

pprint.pprint_run_response(run_response)
