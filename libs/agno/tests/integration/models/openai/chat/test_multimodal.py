from typing import Any

import requests

from agno.agent.agent import Agent
from agno.media import Audio, Image
from agno.models.openai.chat import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools


def _get_audio_input() -> bytes | Any:
    """Fetch an example audio file and return it as base64 encoded string"""
    url = "https://openaiassets.blob.core.windows.net/$web/API/docs/audio/alloy.wav"
    response = requests.get(url)
    response.raise_for_status()
    return response.content


def test_image_input():
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[DuckDuckGoTools(cache_results=True)],
        markdown=True,
        telemetry=False,
        monitoring=False,
    )

    response = agent.run(
        "Tell me about this image and give me the latest news about it.",
        images=[Image(url="https://upload.wikimedia.org/wikipedia/commons/0/0c/GoldenGateBridge-001.jpg")],
    )

    assert "golden" in response.content.lower()


def test_audio_input_bytes():
    wav_data = _get_audio_input()

    # Provide the agent with the audio file and get result as text
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-audio-preview", modalities=["text"]),
        markdown=True,
        telemetry=False,
        monitoring=False,
    )
    response = agent.run("What is in this audio?", audio=[Audio(content=wav_data, format="wav")])

    assert response.content is not None


def test_audio_input_url():
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-audio-preview", modalities=["text"]),
        markdown=True,
        telemetry=False,
        monitoring=False,
    )

    response = agent.run(
        "What is in this audio?",
        audio=[Audio(url="https://openaiassets.blob.core.windows.net/$web/API/docs/audio/alloy.wav")],
    )

    assert response.content is not None


def test_audio_tokens():
    """Assert audio_tokens is populated correctly and returned in the metrics"""
    wav_data = _get_audio_input()

    agent = Agent(
        model=OpenAIChat(
            id="gpt-4o-audio-preview",
            modalities=["text", "audio"],
            audio={"voice": "alloy", "format": "wav"},
        ),
        markdown=True,
    )
    response = agent.run("What is in this audio?", audio=[Audio(content=wav_data, format="wav")])

    audio_tokens = response.metrics.get("audio_tokens")
    input_audio_tokens = response.metrics.get("input_audio_tokens")
    output_audio_tokens = response.metrics.get("output_audio_tokens")

    assert audio_tokens is not None and input_audio_tokens is not None and output_audio_tokens is not None
    assert sum(audio_tokens) > 0
    assert sum(input_audio_tokens) > 0
    assert sum(output_audio_tokens) > 0
