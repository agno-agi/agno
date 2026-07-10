"""MCP Unstructured Transform Agent - parse, enrich, chunk, and embed documents.

This example connects an Agno agent to the hosted Unstructured Transform MCP
server via `mcp-remote`, which handles the browser-based OAuth flow on first
run and caches the token under `~/.mcp-auth/`. Transform turns 60+ document
formats (PDFs, Office docs, HTML, images, email, CSV, RTF, and more) into
structured, enriched, chunked, and embedded output.

The example wires Transform's four MCP tools (request_file_upload_url,
transform_files, check_transform_status, get_transform_results) together with
a small local `upload_file` tool that PUTs file bytes to the signed URL that
Transform returns. The agent orchestrates the whole flow end-to-end.

Example prompts to try:
- "Parse the local file and return parties, effective date, and
   termination clauses as JSON."
- "Extract line items from the local invoice as
   {sku, description, qty, unit_price, total}."
- "Partition the local PDF with hi_res, chunk by title, embed the chunks."

Run: `uv pip install agno mcp anthropic httpx` to install the dependencies.

Setup:
1. Install Node.js (required by `mcp-remote`).
2. Authenticate once via browser:
     npx -y mcp-remote https://mcp.transform.unstructured.io
   Complete the OAuth flow in the tab that opens. The token caches under
   `~/.mcp-auth/`, so subsequent runs are headless.
3. Drop a PDF at TRANSFORM_SAMPLE_PDF (default:
   `<tempfile.gettempdir()>/sample.pdf`, which resolves to `/tmp` on
   Linux, `$TMPDIR` on macOS, and `%TEMP%` on Windows). If unsure of the
   exact path, run once without setting TRANSFORM_SAMPLE_PDF and the
   guard will print it.

Environment variables:
- ANTHROPIC_API_KEY: Required for the default Claude model.
- TRANSFORM_SAMPLE_PDF: Optional path override for the sample file.

Links:
- Docs: https://docs.unstructured.io/transform/overview
- Install docs (per client): https://docs.unstructured.io/transform/install/overview
"""

import asyncio
import os
import tempfile
from pathlib import Path
from textwrap import dedent

import httpx
from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.tools import tool
from agno.tools.mcp import MCPTools
from mcp import StdioServerParameters

TRANSFORM_MCP_URL = "https://mcp.transform.unstructured.io"


@tool
def upload_file(local_path: str, signed_url: str) -> str:
    """Upload local file bytes to a Transform-issued signed PUT URL.

    Use ONLY for the upload step (step 2 of the Transform flow). Do NOT use
    for downloading the parsed output; the download_url from
    get_transform_results is a GET URL and must be fetched with an HTTP GET
    (e.g. via `curl`), not with this tool.

    Args:
        local_path: Absolute or user-expanded path to the local source file.
        signed_url: The signed PUT URL returned by request_file_upload_url.

    Returns:
        A short status string, e.g. "HTTP 200".
    """
    path = Path(local_path).expanduser()
    with open(path, "rb") as f:
        response = httpx.put(signed_url, content=f.read(), timeout=60)
    response.raise_for_status()
    return f"HTTP {response.status_code}"


async def run_agent(task: str) -> None:
    npx_command = "npx.cmd" if os.name == "nt" else "npx"
    server_params = StdioServerParameters(
        command=npx_command,
        args=["-y", "mcp-remote", TRANSFORM_MCP_URL],
    )

    async with MCPTools(server_params=server_params) as mcp_tools:
        agent = Agent(
            name="TransformAgent",
            model=Claude(id="claude-sonnet-4-5"),
            tools=[mcp_tools, upload_file],
            description=(
                "Agent that parses, enriches, chunks, and embeds files "
                "through the Unstructured Transform MCP server."
            ),
            instructions=dedent("""\
                You have access to Unstructured Transform via MCP, plus a
                local `upload_file` tool. `upload_file` is UPLOAD only,
                used at step 2 below. Do not use it to fetch the parsed
                output at step 5; report the download URL to the user
                instead.

                Standard flow for a local file:
                  1. request_file_upload_url -> returns signed URL + file_ref.
                  2. upload_file(local_path, signed_url) -> PUT the bytes.
                  3. transform_files with stage config. The chunk stage
                     requires a 'strategy' argument, for example
                     {"chunk": {"strategy": "chunk_by_title"}}.
                  4. Poll check_transform_status until COMPLETED.
                  5. get_transform_results with output_format json (for
                     Element JSON) or md/html/txt (for rendered). The
                     returned download_url is for GET; do NOT pass it to
                     upload_file.

                Prefer answering follow-up questions from cached results via
                the returned output_ref rather than re-parsing.
                Respect per-request limits: 50 MB per file, 10 files per
                request, 5 concurrent requests.
                If a call returns a quota-exceeded error, surface remaining
                quota and stop the batch cleanly.
            """),
            markdown=True,
        )
        await agent.aprint_response(input=task, stream=True)


if __name__ == "__main__":
    default_sample = Path(tempfile.gettempdir()) / "sample.pdf"
    sample_path = os.getenv("TRANSFORM_SAMPLE_PDF", str(default_sample))
    if not Path(sample_path).expanduser().exists():
        print(
            f"No file at {sample_path}. Drop a PDF there or set "
            "TRANSFORM_SAMPLE_PDF to a valid path, then re-run."
        )
    else:
        asyncio.run(
            run_agent(
                f"Parse the local file at {sample_path}. Use the hi_res "
                "partition strategy, chunk by title, and return the results "
                "as Element JSON. Report the page count and element count."
            )
        )
