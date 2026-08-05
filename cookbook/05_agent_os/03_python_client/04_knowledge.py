"""Upload, monitor, search, and delete AgentOS knowledge content.

Upload processing is asynchronous, so this example polls the concrete
content-status endpoint before listing and searching.

Prerequisites: start ``_server.py`` and set OPENAI_API_KEY.
Run: .venvs/demo/bin/python cookbook/05_agent_os/03_python_client/04_knowledge.py
Try: watch processing move from processing to completed before search runs.
"""

import asyncio

from agno.client import AgentOSClient
from agno.os.routers.knowledge.schemas import ContentStatus

BASE_URL = "http://localhost:7778"


# ---------------------------------------------------------------------------
# Create the Client
# ---------------------------------------------------------------------------


async def wait_until_processed(client: AgentOSClient, content_id: str) -> ContentStatus:
    """Poll an uploaded content item until processing reaches a terminal state."""
    for _ in range(60):
        status = await client.get_knowledge_content_status(content_id)
        print(f"Content status: {status.status.value}")
        if status.status is ContentStatus.COMPLETED:
            return status.status
        if status.status is ContentStatus.FAILED:
            raise RuntimeError(status.status_message or "Knowledge processing failed")
        await asyncio.sleep(0.5)
    raise TimeoutError("Knowledge content did not finish processing")


async def manage_knowledge() -> None:
    """Exercise the full knowledge content lifecycle."""
    client = AgentOSClient(base_url=BASE_URL)

    uploaded = await client.upload_knowledge_content(
        name="Python client notes",
        description="Small document uploaded by the Python client cookbook.",
        text_content=(
            "AgentOS exposes agents, teams, workflows, sessions, memory, "
            "knowledge, and evaluations through one HTTP API."
        ),
        metadata={"source": "03_python_client"},
    )
    print(f"Upload accepted: {uploaded.id}")

    await wait_until_processed(client, uploaded.id)

    content = await client.list_knowledge_content()
    print(f"Knowledge items: {len(content.data)}")

    results = await client.search_knowledge(
        query="What does AgentOS expose?",
        limit=5,
    )
    print(f"Search results: {len(results.data)}")
    for result in results.data:
        print(f"- {result.content}")
        if result.reranking_score is not None:
            print(f"  Reranking score: {result.reranking_score}")

    deleted = await client.delete_knowledge_content(uploaded.id)
    print(f"Deleted content: {deleted.id}")


# ---------------------------------------------------------------------------
# Run the Example
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    asyncio.run(manage_knowledge())
