"""Bilig WorkPaper MCP - formula workbook tools for agents.

This example connects Agno to the Bilig WorkPaper MCP server over stdio. The
server exposes a small spreadsheet-style quote workbook as tools: read cells,
write inputs, recalculate formulas, persist JSON, and export the WorkPaper
document.

The default smoke test does not require an LLM API key. It proves the MCP tool
loop directly:
- list available WorkPaper tools
- read workbook inputs and formulas
- update an input cell
- verify recalculated formula readback
- verify JSON persistence

Run:
    uv pip install agno mcp openai
    python cookbook/91_tools/mcp/bilig_workpaper.py

Agent mode:
    export OPENAI_API_KEY="your_openai_api_key"
    python cookbook/91_tools/mcp/bilig_workpaper.py --agent
"""

import argparse
import asyncio
import json
import tempfile
from pathlib import Path
from textwrap import dedent

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.mcp import MCPTools
from mcp import StdioServerParameters


def bilig_server_params(workpaper_path: Path) -> StdioServerParameters:
    """Return stdio server params for a writable Bilig demo WorkPaper."""
    return StdioServerParameters(
        command="npm",
        args=[
            "exec",
            "--yes",
            "--package",
            "@bilig/workpaper@latest",
            "--",
            "bilig-workpaper-mcp",
            "--workpaper",
            str(workpaper_path),
            "--init-demo-workpaper",
            "--writable",
        ],
    )


async def call_json(mcp_tools: MCPTools, tool_name: str, **arguments) -> dict:
    """Call an MCP tool registered by Agno and parse its JSON text result."""
    tool = mcp_tools.functions[tool_name]
    if tool.entrypoint is None:
        raise RuntimeError(f"{tool_name} has no callable entrypoint")

    result = await tool.entrypoint(**arguments)
    return json.loads(result.content)


async def run_tool_smoke() -> None:
    workpaper_path = (
        Path(tempfile.mkdtemp(prefix="agno-bilig-")) / "quote.workpaper.json"
    )

    async with MCPTools(
        server_params=bilig_server_params(workpaper_path), timeout_seconds=60
    ) as mcp_tools:
        print("Tools:", sorted(mcp_tools.functions))

        inputs = await call_json(mcp_tools, "read_range", range="Inputs!A1:B5")
        summary = await call_json(mcp_tools, "read_range", range="Summary!A1:B5")
        print("Inputs:", inputs["serialized"])
        print("Summary formulas:", summary["serialized"])

        before_arr = await call_json(
            mcp_tools, "read_cell", sheetName="Summary", address="B3"
        )
        edit = await call_json(
            mcp_tools, "set_cell_contents", sheetName="Inputs", address="B3", value=0.4
        )
        after_customers = await call_json(
            mcp_tools, "read_cell", sheetName="Summary", address="B2"
        )
        after_arr = await call_json(
            mcp_tools, "read_cell", sheetName="Summary", address="B3"
        )
        exported = await call_json(
            mcp_tools, "export_workpaper_document", includeConfig=True
        )

        print("ARR before:", before_arr["value"]["value"])
        print("Customers after:", after_customers["value"]["value"])
        print("ARR after:", after_arr["value"]["value"])
        print("Persisted:", edit["checks"]["persisted"])
        print("Restored matches after:", edit["checks"]["restoredMatchesAfter"])
        print("Exported bytes:", exported["serializedBytes"])
        print("WorkPaper path:", workpaper_path)

        assert before_arr["value"]["value"] == 60000
        assert after_customers["value"]["value"] == 8
        assert after_arr["value"]["value"] == 96000
        assert edit["checks"]["persisted"] is True
        assert edit["checks"]["restoredMatchesAfter"] is True
        assert workpaper_path.exists()


async def run_agent(message: str) -> None:
    workpaper_path = (
        Path(tempfile.mkdtemp(prefix="agno-bilig-agent-")) / "quote.workpaper.json"
    )

    async with MCPTools(
        server_params=bilig_server_params(workpaper_path), timeout_seconds=60
    ) as mcp_tools:
        agent = Agent(
            model=OpenAIChat(id="gpt-4o"),
            tools=[mcp_tools],
            instructions=dedent("""\
                You are a workbook automation assistant.

                Use the Bilig WorkPaper tools to inspect workbook inputs, edit input cells,
                recalculate dependent formulas, and verify readback after every write.
                When you change a cell, report the before value, after value, formula output,
                and whether the JSON document was persisted.
            """),
            markdown=True,
        )

        await agent.aprint_response(message, stream=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the Bilig WorkPaper MCP cookbook example."
    )
    parser.add_argument(
        "--agent",
        action="store_true",
        help="Run the Agno agent demo. Requires OPENAI_API_KEY.",
    )
    args = parser.parse_args()

    if args.agent:
        asyncio.run(
            run_agent(
                "Increase the win rate to 40%, then report expected customers, expected ARR, and persistence status."
            )
        )
    else:
        asyncio.run(run_tool_smoke())


if __name__ == "__main__":
    main()
