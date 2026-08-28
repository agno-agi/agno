"""
Multiple Providers — Tools Mode
===============================

When using mode=ContextMode.tools, providers expose raw tools directly
instead of wrapping them in a sub-agent. Without namespacing, tools like
`read_file` from different providers would collide.

Tool namespacing solves this: each provider prefixes its tools with its id.
- WorkspaceContextProvider(id="code") exposes `code_read_file`, `code_list_files`
- WorkspaceContextProvider(id="docs") exposes `docs_read_file`, `docs_list_files`

The agent uses prefixed names to target the right source.

Requires: OPENAI_API_KEY
"""

from pathlib import Path

from agno.agent import Agent
from agno.context.mode import ContextMode
from agno.context.workspace import WorkspaceContextProvider
from agno.models.openai import OpenAIResponses

# Two workspace providers pointing at different directories
code = WorkspaceContextProvider(
    id="code",
    name="Source Code",
    root=Path(__file__).resolve().parents[2] / "libs" / "agno",
    mode=ContextMode.tools,
)

docs = WorkspaceContextProvider(
    id="docs",
    name="Documentation",
    root=Path(__file__).resolve().parents[2] / "cookbook",
    mode=ContextMode.tools,
)

# Combine tools — no collision because of prefixing
agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[*code.get_tools(), *docs.get_tools()],
    instructions=f"{code.instructions()}\n\n{docs.instructions()}",
    markdown=True,
)

if __name__ == "__main__":
    # Show the prefixed tool names
    print("Available tools:")
    for toolkit in code.get_tools():
        for name in toolkit.functions:
            print(f"  - {name}")
    for toolkit in docs.get_tools():
        for name in toolkit.functions:
            print(f"  - {name}")
    print()

    prompt = (
        "Use code_grep_content to find where 'prefix_tools_with_name' is defined, "
        "then use docs_list_files to see what's in cookbook/12_context."
    )
    print(f"> {prompt}\n")
    agent.print_response(prompt)
