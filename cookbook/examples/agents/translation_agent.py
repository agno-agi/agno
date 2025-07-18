# aa
import asyncio
import json
import os
from pathlib import Path
from textwrap import dedent

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.cartesia import CartesiaTools
from agno.utils.media import save_audio

agent_instructions = dedent(
    f"""Follow these steps SEQUENTIALLY to translate text and generate a localized voice note:
    1. Identify the text to translate and the target language from the user request.
    2. Translate the text accurately to the target language. Keep this translated text for the final audio generation step.
    3. Analyze the emotion conveyed by the *translated* text (e.g., neutral, happy, sad, angry, etc.).
    4. Determine the standard 2-letter language code for the target language (e.g., 'fr' for French, 'es' for Spanish).
    5. Call the 'list_voices' tool to get a list of available Cartesia voices. Wait for the result.
    6. Examine the list of voices from the 'list_voices' result. Select the 'id' of an *existing* voice that:
       a) Matches the target language code (from step 4).
       b) Best reflects the analyzed emotion (from step 3).
    7. Call the 'localize_voice' tool to create a new voice. Provide the following arguments:
       - 'voice_id': The 'base_voice_id' selected in step 6.
       - 'name': A suitable name for the new voice (e.g., "French Happy Female").
       - 'description': A description reflecting the language and emotion.
       - 'language': The target language code (from step 4).
       - 'original_speaker_gender': User specified gender or the selected base voice gender.
       Wait for the result of this tool call.
    8. Check the result of the 'localize_voice' tool call from step 8:
       a) If the call was successful and returned the details of the newly created voice, extract the 'id' of this **new** voice. This is the 'final_voice_id'.
    9. Call the 'text_to_speech' tool to generate the audio. Provide:
        - 'transcript': The translated text from step 2.
        - 'voice_id': The 'final_voice_id' determined in step 9.
    """
)

agent = Agent(
    name="Emotion-Aware Translator Agent",
    description="Translates text, analyzes emotion, selects a suitable voice,creates a localized voice, and generates a voice note (audio file) using Cartesia TTStools.",
    instructions=agent_instructions,
    model=OpenAIChat(id="gpt-4o"),
    tools=[CartesiaTools(voice_localize_enabled=True)],
    show_tool_calls=True,
)

agent.print_response(
    "Convert this phrase 'hello! how are you? Tell me more about the weather in Paris?' to French and create a voice note"
)
response = agent.run_response

print("\nChecking for Audio Artifacts on Agent...")
if response.audio:
    save_audio(
        base64_data=response.audio[0].base64_audio, output_path="tmp/greeting.mp3"
    )
