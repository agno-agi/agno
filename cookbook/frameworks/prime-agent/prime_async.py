"""Exercise async non-streaming runs and streaming response printing.

Requires an installed, authenticated prime-agent CLI.
"""

import asyncio
from os import getenv

from agno.agents.prime import PrimeAgent
from agno.run.base import RunStatus

agent = PrimeAgent(
    name="Prime Async",
    cwd=getenv("PRIME_AGENT_CWD", "."),
    timeout=120,
)


async def main() -> None:
    run = await agent.arun("Reply with exactly ASYNC_OK.")
    assert run.status == RunStatus.completed, run.content
    assert "ASYNC_OK" in str(run.content), run.content
    print(f"Non-streaming run: {run.run_id} | {run.status.value}")

    streamed = await agent.aprint_response(
        "What is 17 times 3? Reply with just the number.",
        stream=True,
    )
    assert streamed.status == RunStatus.completed, streamed.content
    assert str(streamed.content).strip() == "51", streamed.content
    print(f"Streaming run: {streamed.run_id} | {streamed.status.value}")


if __name__ == "__main__":
    asyncio.run(asyncio.wait_for(main(), timeout=260))
