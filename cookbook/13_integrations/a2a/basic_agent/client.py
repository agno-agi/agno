from typing import Any
from uuid import uuid4

import httpx
from a2a.client import A2AClient
from a2a.types import (
    MessageSendParams,
    SendMessageRequest,
    SendStreamingMessageRequest,  # noqa: F401
)


async def main() -> None:
    async with httpx.AsyncClient() as httpx_client:
        client = await A2AClient.get_client_from_agent_card_url(
            httpx_client, "http://localhost:9999"
        )
        send_message_payload: dict[str, Any] = {
            "message": {
                "role": "user",
                "parts": [
                    {
                        "type": "text",
                        "text": "Hello! What can you tell me about the weather in Tokyo?",
                    }
                ],
                "messageId": uuid4().hex,
            },
        }
        request = SendMessageRequest(params=MessageSendParams(**send_message_payload))

        response = await client.send_message(request)
        print(response.model_dump(mode="json", exclude_none=True))

        # streaming_request = SendStreamingMessageRequest(
        #     params=MessageSendParams(**send_message_payload)
        # )

        # stream_response = client.send_message_streaming(streaming_request)
        # async for chunk in stream_response:
        #     print(chunk.model_dump(mode='json', exclude_none=True))


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
