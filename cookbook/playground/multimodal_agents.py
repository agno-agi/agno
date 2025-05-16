"""
1. Install dependencies: `pip install openai sqlalchemy 'fastapi[standard]' agno requests`
2. Authenticate with agno: `agno setup`
3. Run the agent: `python cookbook/playground/multimodal_agent.py`

Docs on Agent UI: https://docs.agno.com/agent-ui
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.models.response import FileType
from agno.playground import Playground, serve_playground_app
from agno.storage.sqlite import SqliteStorage
from agno.tools.dalle import DalleTools
from agno.tools.eleven_labs import ElevenLabsTools
from agno.tools.fal import FalTools
from agno.tools.giphy import GiphyTools
from agno.tools.models_labs import ModelsLabTools

image_agent_storage_file: str = "tmp/image_agent.db"

image_agent = Agent(
    name="DALL-E Image Agent",
    agent_id="image_agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[DalleTools(model="dall-e-3", size="1792x1024", quality="hd", style="vivid")],
    description="You are an AI agent that can generate images using DALL-E.",
    instructions=[
        "When the user asks you to create an image, use the `create_image` tool to create the image.",
        "Don't provide the URL of the image in the response. Only describe what image was generated.",
    ],
    markdown=True,
    add_history_to_messages=True,
    add_datetime_to_instructions=True,
    storage=SqliteStorage(
        table_name="image_agent",
        db_file=image_agent_storage_file,
        auto_upgrade_schema=True,
    ),
)

ml_gif_agent = Agent(
    name="ModelsLab GIF Agent",
    agent_id="ml_gif_agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[ModelsLabTools(wait_for_completion=True, file_type=FileType.GIF)],
    description="You are an AI agent that can generate gifs using the ModelsLabs API.",
    instructions=[
        "When the user asks you to create an image, use the `generate_media` tool to create the image.",
        "Don't provide the URL of the image in the response. Only describe what image was generated.",
    ],
    markdown=True,
    add_history_to_messages=True,
    add_datetime_to_instructions=True,
    storage=SqliteStorage(
        table_name="ml_gif_agent",
        db_file=image_agent_storage_file,
        auto_upgrade_schema=True,
    ),
)

ml_music_agent = Agent(
    name="ModelsLab Music Agent",
    agent_id="ml_music_agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[ModelsLabTools(wait_for_completion=True, file_type=FileType.MP3)],
    description="You are an AI agent that can generate music using the ModelsLabs API.",
    instructions=[
        "When generating music, use the `generate_media` tool with detailed prompts that specify:",
        "- The genre and style of music (e.g., classical, jazz, electronic)",
        "- The instruments and sounds to include",
        "- The tempo, mood and emotional qualities",
        "- The structure (intro, verses, chorus, bridge, etc.)",
        "Create rich, descriptive prompts that capture the desired musical elements.",
        "Focus on generating high-quality, complete instrumental pieces.",
        "Keep responses simple and only confirm when music is generated successfully.",
        "Do not include any file names, URLs or technical details in responses.",
    ],
    markdown=True,
    add_history_to_messages=True,
    add_datetime_to_instructions=True,
    storage=SqliteStorage(
        table_name="ml_music_agent",
        db_file=image_agent_storage_file,
        auto_upgrade_schema=True,
    ),
)

ml_video_agent = Agent(
    name="ModelsLab Video Agent",
    agent_id="ml_video_agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[ModelsLabTools(wait_for_completion=True, file_type=FileType.MP4)],
    description="You are an AI agent that can generate videos using the ModelsLabs API.",
    instructions=[
        "When the user asks you to create a video, use the `generate_media` tool to create the video.",
        "Don't provide the URL of the video in the response. Only describe what video was generated.",
    ],
    markdown=True,
    add_history_to_messages=True,
    add_datetime_to_instructions=True,
    storage=SqliteStorage(
        table_name="ml_video_agent",
        db_file=image_agent_storage_file,
        auto_upgrade_schema=True,
    ),
)

fal_agent = Agent(
    name="Fal Video Agent",
    agent_id="fal_agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[FalTools("fal-ai/hunyuan-video")],
    description="You are an AI agent that can generate videos using the Fal API.",
    instructions=[
        "When the user asks you to create a video, use the `generate_media` tool to create the video.",
        "Don't provide the URL of the video in the response. Only describe what video was generated.",
    ],
    markdown=True,
    add_history_to_messages=True,
    add_datetime_to_instructions=True,
    storage=SqliteStorage(
        table_name="fal_agent",
        db_file=image_agent_storage_file,
        auto_upgrade_schema=True,
    ),
)

gif_agent = Agent(
    name="Gif Generator Agent",
    agent_id="gif_agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[GiphyTools()],
    description="You are an AI agent that can generate gifs using Giphy.",
    instructions=[
        "When the user asks you to create a gif, come up with the appropriate Giphy query and use the `search_gifs` tool to find the appropriate gif.",
        "Don't return the URL, only describe what you created.",
    ],
    markdown=True,
    add_history_to_messages=True,
    add_datetime_to_instructions=True,
    storage=SqliteStorage(
        table_name="gif_agent",
        db_file=image_agent_storage_file,
        auto_upgrade_schema=True,
    ),
)

audio_agent = Agent(
    name="Audio Generator Agent",
    agent_id="audio_agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        ElevenLabsTools(
            voice_id="JBFqnCBsd6RMkjVDRZzb",
            model_id="eleven_multilingual_v2",
            target_directory="audio_generations",
        )
    ],
    description="You are an AI agent that can generate audio using the ElevenLabs API.",
    instructions=[
        "When the user asks you to generate audio, use the `text_to_speech` tool to generate the audio.",
        "You'll generate the appropriate prompt to send to the tool to generate audio.",
        "You don't need to find the appropriate voice first, I already specified the voice to user."
        "Don't return file name or file url in your response or markdown just tell the audio was created successfully.",
        "The audio should be long and detailed.",
    ],
    markdown=True,
    add_history_to_messages=True,
    add_datetime_to_instructions=True,
    storage=SqliteStorage(
        table_name="audio_agent",
        db_file=image_agent_storage_file,
        auto_upgrade_schema=True,
    ),
)


app = Playground(
    agents=[
        image_agent,
        ml_gif_agent,
        ml_music_agent,
        ml_video_agent,
        fal_agent,
        gif_agent,
        audio_agent,
    ]
).get_app(use_async=False)

if __name__ == "__main__":
    serve_playground_app("multimodal_agents:app", reload=True)
