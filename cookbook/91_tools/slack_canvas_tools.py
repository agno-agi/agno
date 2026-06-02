"""Run: pip install openai slack-sdk

Requires these bot scopes in your Slack app:
- canvases:read, canvases:write (for canvas operations)
- files:read (for listing and reading canvas content)

Set the SLACK_TOKEN environment variable before running.

Supported canvas markdown: headings, bold, italic, strikethrough, inline code,
bullet/numbered lists, checklists (- [ ] / - [x]), code blocks, links, emojis,
blockquotes, tables (max 300 cells), and horizontal rules.

Note: list_canvases uses files.list which only returns channel canvases.
Standalone canvases (created via create_canvas) need their canvas_id saved
or use create_channel_canvas to attach them to a channel for discovery.
"""

from agno.agent import Agent
from agno.tools.slack import SlackTools

# Agent with Canvas tools enabled alongside default messaging tools
agent = Agent(
    tools=[SlackTools(enable_canvas=True)],
    markdown=True,
)

if __name__ == "__main__":
    # Create a canvas and immediately edit it using the returned canvas_id
    agent.print_response(
        "Create a canvas titled 'Sprint Planning' with a '## Tasks' section "
        "containing 3 checklist items. Then use the canvas_id to add a "
        "'## Notes' section with a blockquote at the end.",
        stream=True,
    )

    # Read and update an existing canvas by ID
    agent.print_response(
        "Read the RBAC Working Group canvas (F0B7GBTJN91) and summarize its content.",
        stream=True,
    )
