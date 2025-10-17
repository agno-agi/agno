#!/usr/bin/env python3
"""
Minimal test to check OpenRouter Gemini image generation response structure
"""
import json
from agno.agent import Agent
from agno.models.openrouter import OpenRouter

# Create a simple agent with Gemini image generation
agent = Agent(
    name="Nano Banana via OpenRouter",
    model=OpenRouter(
        id="google/gemini-2.5-flash-image-preview",
        modalities=["image", "text"]
    ),
    markdown=False
)



response = agent.run("Generate a simple red circle")


for i, msg in enumerate(response.messages):
    print(f"\nMessage {i}:")
    print(f"  Role: {msg.role}")
    print(f"  Content type: {type(msg.content)}")
    print(f"  Content: {str(msg.content)[:200] if msg.content else 'None'}")

    # Check for provider_data (raw API response)
    if hasattr(msg, 'provider_data') and msg.provider_data:
        print(f"  provider_data keys: {list(msg.provider_data.keys())}")
        print(f"  provider_data: {json.dumps(msg.provider_data, indent=2, default=str)[:1000]}")

    # Check for additional fields
    if hasattr(msg, 'images'):
        print(f"  msg.images: {msg.images}")
    if hasattr(msg, 'image_output'):
        print(f"  msg.image_output: {msg.image_output}")
    if hasattr(msg, 'video_output'):
        print(f"  msg.video_output: {msg.video_output}")
    if hasattr(msg, 'audio_output'):
        print(f"  msg.audio_output: {msg.audio_output}")

print("\nFull Response Dict:")
try:
    response_dict = response.model_dump() if hasattr(response, 'model_dump') else vars(response)
    print(json.dumps(response_dict, indent=2, default=str)[:2000])
except Exception as e:
    print(f"Error converting to dict: {e}")
    print("\nRaw response:", response)

print("\nTest complete!")


# Full Response Dict: image_output now has data
# {
#   "run_id": "87fd8001-d426-42bc-9069-3cfd07d494c6",
#   "agent_id": "test-agent",
#   "agent_name": "Test Agent",
#   "session_id": "4f1b8676-45b3-48ab-b5bd-7f04ec79e70a",
#   "parent_run_id": null,
#   "workflow_id": null,
#   "user_id": null,
#   "input": "RunInput(input_content='Generate a simple red circle', images=None, videos=None, audios=None, files=None)",
#   "content": "",
#   "content_type": "str",
#   "reasoning_content": null,
#   "reasoning_steps": null,
#   "reasoning_messages": null,
#   "model_provider_data": null,
#   "model": "google/gemini-2.5-flash-image-preview",
#   "model_provider": "OpenRouter",
#   "messages": [
#     "role='user' content='Generate a simple red circle' name=None tool_call_id=None tool_calls=None audio=None images=None videos=None files=None audio_output=None image_output=None video_output=None file_output=None redacted_reasoning_content=None provider_data=None citations=None reasoning_content=None tool_name=None tool_args=None tool_call_error=None stop_after_tool_call=False add_to_agent_memory=True from_history=False metrics=Metrics(input_tokens=0, output_tokens=0, total_tokens=0, audio_input_tokens=0, audio_output_tokens=0, audio_total_tokens=0, cache_read_tokens=0, cache_write_tokens=0, reasoning_tokens=0, timer=None, time_to_first_token=None, duration=None, provider_metrics=None, additional_metrics=None) references=None created_at=1760340841",
#     "role='assistant' content='' name=None tool_call_id=None tool_calls=None audio=None images=None videos=None files=None audio_output=None image_output='data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAABAAAAAQACAIAAADwf7zUAAAAiXpUWHRSYXcgcHJvZmlsZSB0eXBlIGlwdGMAAAiZTYwxDgIxDAT7vOKekDjrtV1T0VHwgbtcIiEhgfh/QaDgmGlWW0w6X66n5fl6jNu9p+ULkapDENgzpj+Kl5aFfa6KnYWgSjZjGOiSYRxTY/v8KIijI/rXyc236kHdAK22RvHVummEN+91ML0BQ+siou79WmMAAAKHaVRYdFhNTDpjb20uYWRvYmUueG1wAAAAAAA8P3hwYWNrZXQgYmVnaW49Iu+7vyIgaWQ9Ilc1TTBNcENlaGlIenJlU3pOVGN6a2M5ZCI/PiA8eDp4bXBtZXRhIHhtbG5zOng9ImFkb2JlOm5zOm1ldGEvIiB4OnhtcHRrPSJYTVAgQ29yZSA1LjUuMCI+IDxyZGY
