import os

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.utils.audio import write_audio_to_file
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# OpenAI API Key
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

os.makedirs("tmp", exist_ok=True)


def generate_podcast(topic, voice="alloy"):
    """
    Generates a podcast script using a agnodata Agent and converts it to speech using OpenAI TTS.

    Args:
        topic (str): The topic of the podcast.
        voice (str): Voice model for OpenAI TTS. Options: ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]
    """

    # Create a agnodata agent to generate the podcast script
    audio_agent = Agent(
        system_message="You are a podcast scriptwriter specializing in concise and engaging narratives. Your task is to research a given topic using Exa and DuckDuckGo, gather relevant insights, and compose a short, compelling podcast script.",
        instructions="""### **Instructions:**
            1. **Research Phase:**
            - Use Exa and DuckDuckGo to gather the most recent and relevant information on the given topic.
            - Prioritize trustworthy sources such as news sites, academic articles, or well-established blogs.
            - Identify key points, statistics, expert opinions, and interesting facts.

            2. **Scripting Phase:**
            - Write a concise podcast script in a conversational tone.
            - Begin with a strong hook to capture the listener's attention.
            - Present the key insights in an engaging, easy-to-follow manner.
            - Include a smooth transition between ideas to maintain narrative flow.
            - End with a closing remark that summarizes the main takeaways and encourages further curiosity.

            ### **Formatting Guidelines:**
            - Use simple, engaging language.
            - Keep the script under 300 words (around 2 minutes of audio).
            - Write in a natural, spoken format, avoiding overly formal or technical jargon.
            - Start with a short intro of the topic, then cover the main content, and conclude.

            ### **Example Output:**
            #### **Today we will be covering the topic The Future of AI in Healthcare**
            "Imagine walking into a hospital where AI instantly diagnoses your illness, prescribes treatment, and even assists in surgery. Sounds like science fiction? Well, it's closer to reality than you think! Welcome to today's episode, where we explore how AI is revolutionizing healthcare."

            "AI is making waves in medical research, diagnostics, and patient care. For instance, Google's DeepMind developed an AI that can detect over 50 eye diseases with a single scan—just as accurately as top doctors! Meanwhile, robotic surgeries assisted by AI are reducing complications and recovery time for patients. But it's not just about tech—AI is also addressing healthcare accessibility. In rural areas, AI-powered chatbots provide medical advice where doctors are scarce."

            "While AI in healthcare is promising, it also raises ethical concerns. Who takes responsibility for a wrong diagnosis? How do we ensure data privacy? These are crucial questions for the future. One thing's for sure—AI is here to stay, and it's reshaping medicine as we know it. Thanks for tuning in, and see you next time!"
            """,
        model=OpenAIChat(
            id="gpt-4o-audio-preview",
            modalities=["text", "audio"],
            audio={"voice": voice, "format": "wav"},
        ),
        tools=[DuckDuckGoTools()],
    )

    # Generate the podcast script
    audio_agent.run(f"Write the content of podcast for the topic: {topic}")
    audio_file_path = "tmp/generated_podcast.wav"

    if audio_agent.run_response.response_audio is not None:
        audio_content = audio_agent.run_response.response_audio.content

        if audio_content:
            write_audio_to_file(
                audio=audio_content,
                filename=audio_file_path,
            )
            return audio_file_path
    return None
