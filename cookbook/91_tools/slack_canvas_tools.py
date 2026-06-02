"""Run: pip install openai slack-sdk

Requires canvases:read and canvases:write bot scopes in your Slack app.
Set the SLACK_TOKEN environment variable before running.

Supported canvas markdown: headings, bold, italic, strikethrough, inline code,
bullet/numbered lists, checklists (- [ ] / - [x]), code blocks, links, emojis,
blockquotes, tables (max 300 cells), and horizontal rules.
"""

from agno.agent import Agent
from agno.tools.slack import SlackTools

# Agent with Canvas tools enabled alongside default messaging tools
agent = Agent(
    tools=[SlackTools(enable_canvas=True)],
    markdown=True,
)

if __name__ == "__main__":
    # Create a canvas with rich content
    agent.print_response(
        "Create a canvas titled 'Sprint Planning' with these sections: "
        "a checklist under '## Tasks' with 3 items, "
        "a table under '## Timeline' with columns Task/Owner/Status, "
        "and a '## Notes' section with a blockquote.",
        stream=True,
    )

    # Read and update an existing canvas
    agent.print_response(
        "List all canvases, read the 'Sprint Planning' canvas, "
        "then add a new task '- [ ] Write release notes' to the Tasks section.",
        stream=True,
    )
