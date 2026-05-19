"""
Streaming Client Demo
=====================

Connect to a running Agno A2A server using the official `a2a-sdk` client and
iterate over a streaming `message/stream` response, printing each
TaskStatusUpdateEvent and the final Task. Proves that Agno's streaming
interface conforms to the A2A 1.0 spec.

Prerequisites:
    .venvs/demo/bin/python -m pip install -U "a2a-sdk>=1.0"

Start a target server in another terminal (the weather agent on port 7770):
    .venvs/demo/bin/python cookbook/05_agent_os/interfaces/a2a/multi_agent_a2a/weather_agent.py

Then run this script:
    .venvs/demo/bin/python cookbook/05_agent_os/interfaces/a2a/multi_agent_a2a/streaming_client_demo.py
"""

import asyncio
from uuid import uuid4

from a2a.client import create_client
from a2a.types import Message, Part, Role, SendMessageRequest

TARGET_BASE_URL = "http://localhost:7770/a2a/agents/weather-reporter-agent/v1"
PROMPT = "What is the weather in Tokyo right now? Be concise."


async def main() -> None:
    request = SendMessageRequest(
        message=Message(
            message_id=str(uuid4()),
            role=Role.ROLE_USER,
            parts=[Part(text=PROMPT, media_type="text/plain")],
        )
    )
    client = create_client(TARGET_BASE_URL)
    async with client:
        print(f"Connecting to {TARGET_BASE_URL}")
        print(f"Prompt: {PROMPT}\n")

        async for response in client.send_message(request):
            kind = response.WhichOneof("payload")
            if kind == "status_update":
                evt = response.status_update
                print(f"[status_update] state={evt.status.state} task_id={evt.task_id}")
            elif kind == "artifact_update":
                evt = response.artifact_update
                print(f"[artifact_update] artifact_id={evt.artifact.artifact_id}")
            elif kind == "message":
                msg = response.message
                text = "".join(
                    p.text for p in msg.parts if p.WhichOneof("content") == "text"
                )
                if text:
                    print(f"[message] {text}")
            elif kind == "task":
                task = response.task
                print(f"\n[final task] id={task.id} state={task.status.state}")
                for entry in task.history:
                    body = "".join(
                        p.text for p in entry.parts if p.WhichOneof("content") == "text"
                    )
                    if body:
                        print(f"  - {body}")


if __name__ == "__main__":
    asyncio.run(main())
