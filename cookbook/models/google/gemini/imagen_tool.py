"""🔧 Example: Using the GeminiTools Toolkit for Image Generation

Make sure you have set the GOOGLE_API_KEY environment variable.
Example prompts to try:
- "Create a surreal painting of a floating city in the clouds at sunset"
- "Generate a photorealistic image of a cozy coffee shop interior"
- "Design a cute cartoon mascot for a tech startup, vector style"
- "Create an artistic portrait of a cyberpunk samurai in a rainy city"

Run `pip install google-genai agno` to install the necessary dependencies.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.models.gemini import GeminiTools
from agno.utils.media import save_base64_data

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[GeminiTools()],
)

agent.print_response(
    "Create an artistic portrait of a cyberpunk samurai in a rainy city",
)
response = agent.run_response
if response and response.images:
    save_base64_data(str(response.images[0].content), "tmp/cyberpunk_samurai.png")
