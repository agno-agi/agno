"""
Multimodal AgentOS Demo

Registers representative agents from the multimodal cookbook folder into a single AgentOS app.

Note: This file only defines agents and does not execute runs at import time.
Start the server and interact with any agent through the UI or API.
"""

from typing import List, Optional, Sequence

from agno.agent import Agent
from agno.models.google import Gemini
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.tools import Toolkit
from agno.tools.dalle import DalleTools
from agno.tools.fal import FalTools
from agno.tools.models_labs import ModelsLabTools
from agno.tools.moviepy_video import MoviePyVideoTools
from agno.tools.openai import OpenAITools
from agno.tools.replicate import ReplicateTools
from pydantic import BaseModel, Field


# ------------------------------
# Structured output schema
# ------------------------------
class MovieScript(BaseModel):
    name: str = Field(..., description="Give a name to this movie")
    setting: str = Field(
        ..., description="Provide a nice setting for a blockbuster movie."
    )
    characters: List[str] = Field(..., description="Name of characters for this movie.")
    storyline: str = Field(
        ..., description="3 sentence storyline for the movie. Make it exciting!"
    )


# ------------------------------
# Example toolkits from folder examples
# ------------------------------
class DocumentProcessingTools(Toolkit):
    def __init__(self):
        tools = [self.extract_text_from_pdf]
        super().__init__(name="document_processing_tools", tools=tools)

    def extract_text_from_pdf(self, files: Optional[Sequence["File"]] = None) -> str:  # type: ignore[name-defined]
        """
        Extract text from uploaded PDF files using OCR (simulated).
        Files passed to the agent are injected here when the tool is called.
        """
        if not files:
            return "No files were uploaded to process."
        extracted_texts: List[str] = []
        for i, file in enumerate(files):
            if getattr(file, "content", None):
                file_size = len(file.content)  # type: ignore[arg-type]
                extracted_texts.append(
                    (
                        f"[SIMULATED OCR RESULT FOR FILE {i + 1}]\n"
                        f"Document processed successfully!\n"
                        f"File size: {file_size} bytes\n\n"
                        f"Sample extracted content:\n"
                        f"\"This is a sample document with important information about quarterly sales figures.\n"
                        f"Q1 Revenue: $125,000\nQ2 Revenue: $150,000\nQ3 Revenue: $175,000\n\n"
                        f"The growth trend shows a 20% increase quarter over quarter.\""
                    )
                )
            else:
                extracted_texts.append(f"File {i + 1}: Content is empty or inaccessible.")
        return "\n\n".join(extracted_texts)


class ImageAnalysisTools(Toolkit):
    def __init__(self):
        tools = [self.analyze_images, self.count_images]
        super().__init__(name="image_analysis_tools", tools=tools)

    def analyze_images(self, images: Optional[Sequence["Image"]] = None) -> str:  # type: ignore[name-defined]
        if not images:
            return "No images available to analyze."
        analysis_results: List[str] = []
        for i, image in enumerate(images):
            if getattr(image, "url", None):
                analysis_results.append(f"Image {i + 1}: URL-based image at {image.url}")
            elif getattr(image, "content", None):
                analysis_results.append(
                    f"Image {i + 1}: Content-based image ({len(image.content)} bytes)"  # type: ignore[arg-type]
                )
            else:
                analysis_results.append(f"Image {i + 1}: Unknown image format")
        return f"Found {len(images)} images:\n" + "\n".join(analysis_results)

    def count_images(self, images: Optional[Sequence["Image"]] = None) -> str:  # type: ignore[name-defined]
        if not images:
            return "0 images available"
        return f"{len(images)} images available"


# ------------------------------
# Agents aggregated from the multimodal folder
# ------------------------------

# Image understanding/generation
image_to_text_agent = Agent(
    id="image-to-text",
    name="Image to Text",
    model=OpenAIChat(id="gpt-4o"),
    markdown=True,
)

image_input_high_fidelity_agent = Agent(
    id="image-input-high-fidelity",
    name="High Fidelity Image Input",
    model=OpenAIChat(id="gpt-4o"),
    add_history_to_context=True,
    markdown=True,
    store_media=True,
)

image_input_multi_turn_agent = Agent(
    id="image-input-multi-turn",
    name="Image Input Multi Turn",
    model=OpenAIChat(id="gpt-4o"),
    add_history_to_context=True,
    markdown=True,
    store_media=True,
)

image_to_structured_output_agent = Agent(
    id="image-to-structured-output",
    name="Image to Structured Output",
    model=OpenAIChat(id="gpt-4o"),
    output_schema=MovieScript,
)

dalle_intermediate_agent = Agent(
    id="dalle-intermediate",
    name="DALL-E Intermediate Steps",
    model=OpenAIChat(id="gpt-4o"),
    tools=[DalleTools()],
    description="Create images using DALL-E and stream intermediate steps.",
    instructions=[
        "When asked to create an image, use the DALL-E tool.",
        "Return the image URL using standard markdown: ![description](url)",
    ],
    markdown=True,
)

dalle_image_generator_agent = Agent(
    id="dalle-image-generator",
    name="DALL-E Image Generator",
    model=OpenAIChat(id="gpt-4.1"),
    tools=[DalleTools()],
)

dalle_history_agent = Agent(
    id="dalle-history-agent",
    name="DALL-E History Agent",
    tools=[DalleTools()],
    add_history_to_context=True,
)

fal_image_to_image_agent = Agent(
    id="image-to-image",
    name="Image to Image Agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[FalTools()],
    markdown=True,
    instructions=[
        "Use the image_to_image tool to generate the image.",
        "Return the image URL as provided without formatting.",
    ],
)

# Audio
image_to_audio_agent = Agent(
    id="text-to-audio",
    name="text to Audio Narration",
    model=OpenAIChat(
        id="gpt-4o-audio-preview",
        modalities=["text", "audio"],
        audio={"voice": "sage", "format": "pcm16"},
    ),
)

audio_input_output_agent = Agent(
    id="audio-input-output",
    name="Audio Input Output",
    model=OpenAIChat(
        id="gpt-4o-audio-preview",
        modalities=["text", "audio"],
        audio={"voice": "sage", "format": "pcm16"},
    ),
    markdown=True,
)

audio_to_text_agent = Agent(
    id="audio-to-text",
    name="Audio To Text",
    model=Gemini(id="gemini-2.0-flash-exp"),
    markdown=True,
)

audio_streaming_agent = Agent(
    id="audio-streaming",
    name="Audio Streaming",
    model=OpenAIChat(
        id="gpt-4o-audio-preview",
        modalities=["text", "audio"],
        audio={"voice": "alloy", "format": "pcm16"},
    ),
)

audio_multi_turn_agent = Agent(
    id="audio-multi-turn",
    name="Audio Multi Turn",
    model=OpenAIChat(
        id="gpt-4o-audio-preview",
        modalities=["text", "audio"],
        audio={"voice": "sage", "format": "pcm16"},
    ),
    add_history_to_context=True,
)

audio_sentiment_analysis_agent = Agent(
    id="audio-sentiment-analysis",
    name="Audio Sentiment Analysis",
    model=Gemini(id="gemini-2.0-flash-exp"),
    add_history_to_context=True,
    markdown=True,
)

# Video
video_models_labs_agent = Agent(
    id="video-generator-modelslab",
    name="Video Generator (ModelsLab)",
    model=OpenAIChat(id="gpt-4o"),
    tools=[ModelsLabTools()],
    description="Generate videos using the ModelsLabs API.",
    instructions=[
        "When asked to create a video, use the generate_media tool.",
        "The UI will display the video; you do not need to return the URL.",
    ],
    markdown=True,
)

video_replicate_agent = Agent(
    id="video-generator-replicate",
    name="Video Generator (Replicate)",
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        ReplicateTools(
            model="tencent/hunyuan-video:847dfa8b01e739637fc76f480ede0c1d76408e1d694b830b5dfb8e547bf98405"
        )
    ],
    description="Generate videos using the Replicate API.",
    instructions=[
        "When asked to create a video, use the generate_media tool.",
        "Return the raw video URL without additional formatting.",
    ],
    markdown=True,
)

# video_caption_tools = MoviePyVideoTools(
#     process_video=True, generate_captions=True, embed_captions=True
# )
# video_caption_agent = Agent(
#     id="video-caption-generator",
#     name="Video Caption Generator Agent",
#     model=OpenAIChat(id="gpt-4o"),
#     tools=[video_caption_tools, OpenAITools()],
#     description="Generate and embed captions for provided videos.",
#     instructions=[
#         "Extract audio, transcribe, create SRT captions, then embed captions in the video.",
#     ],
#     markdown=True,
# )

# video_to_shorts_agent = Agent(
#     id="video-to-shorts",
#     name="Video2Shorts",
#     description="Process videos and generate engaging shorts.",
#     model=Gemini(id="gemini-2.0-flash-exp"),
#     markdown=True,
#     instructions=[
#         "Analyze the provided video only; do not reference external sources.",
#         "Return analysis in a table with Start Time | End Time | Description | Importance Score.",
#         "Use MM:SS timestamps and scores from 1-10, focusing on 15-60s segments.",
#     ],
# # )

# # Tool-media access examples
# document_processing_agent = Agent(
#     id="document-processing-agent",
#     name="Document Processing Agent",
#     model=Gemini(id="gemini-2.5-pro"),
#     tools=[DocumentProcessingTools()],
#     description=(
#         "Process uploaded documents and extract text using a tool; summarize results."
#     ),
#     debug_mode=True,
#     send_media_to_model=False,
#     store_media=True,
# )

# joint_media_test_agent = Agent(
#     id="joint-media-test-agent",
#     name="Joint Media Test Agent",
#     model=OpenAIChat(id="gpt-4o"),
#     tools=[ImageAnalysisTools(), DalleTools()],
#     description="Generate and analyze images using joint media access.",
#     debug_mode=True,
#     add_history_to_context=True,
#     send_media_to_model=False,
# )


# ------------------------------
# AgentOS app
# ------------------------------
all_agents = [
    image_to_text_agent,
    image_input_high_fidelity_agent,
    image_input_multi_turn_agent,
    image_to_structured_output_agent,
    dalle_intermediate_agent,
    dalle_image_generator_agent,
    dalle_history_agent,
    fal_image_to_image_agent,
    image_to_audio_agent,
    audio_input_output_agent,
    audio_to_text_agent,
    audio_streaming_agent,
    audio_multi_turn_agent,
    audio_sentiment_analysis_agent,
    video_models_labs_agent,
    video_replicate_agent,
    # video_caption_agent,
    # video_to_shorts_agent,
    # document_processing_agent,
    # joint_media_test_agent,
]

agent_os = AgentOS(
    id="multimodal-demo",
    agents=all_agents,
)
app = agent_os.get_app()


if __name__ == "__main__":
    agent_os.serve(app="demo:app", port=7777)


