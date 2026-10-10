"""Local MCP fixture: record a side effect and optionally wait at a test gate."""

import os
import time

from ledger import connect
from mcp.server.mcpserver import MCPServer

mcp = MCPServer("readiness-fixture")


@mcp.tool()
def checkpoint(case_id: str, step: str, wait: bool = False, fail: bool = False) -> str:
    """Record a receipt, optionally wait for the test controller, then return proof."""
    with connect() as db:
        db.execute(
            "INSERT INTO receipts(case_id, step, replica, created) VALUES (?, ?, ?, ?)",
            (case_id, step, os.environ["HARNESS_REPLICA"], time.time()),
        )
    if fail:
        raise ValueError("Deliberate fixture tool failure")
    if wait:
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            with connect() as db:
                row = db.execute(
                    "SELECT released FROM gates WHERE case_id=?", (case_id,)
                ).fetchone()
            if row and row[0]:
                break
            time.sleep(0.2)
        else:
            raise TimeoutError("Fixture gate was not released in 90 seconds")
    return f"RECEIPT:{case_id}:{step}"


if __name__ == "__main__":
    mcp.run(transport="stdio")
