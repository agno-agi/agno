"""Slack Canvas Tools - persistent, editable documents in Slack.

Environment:
    SLACK_TOKEN     Bot token with canvases:read, canvases:write, files:read scopes

Run: pip install openai slack-sdk
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.slack import SlackTools

agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[
        SlackTools(
            enable_list_canvases=True,
            enable_read_canvas=True,
            enable_create_canvas=True,
            enable_edit_canvas=True,
            enable_delete_canvas=True,
            enable_lookup_canvas_sections=True,
        )
    ],
    markdown=True,
)

if __name__ == "__main__":
    # Create a canvas and edit it
    agent.print_response(
        "Create a canvas titled 'Sprint Planning' with a '## Tasks' section "
        "containing 3 checklist items. Then add a '## Notes' section at the end.",
        stream=True,
    )
