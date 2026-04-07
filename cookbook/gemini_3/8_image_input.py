"""
Image Understanding - Analyze and Describe Images
===================================================
Pass images to Gemini via URL or local file for analysis, description, and Q&A.

Key concepts:
- Image(url=...): Pass an image from a URL
- Image(filepath=...): Pass a local image file
- images=[...]: List of Image objects passed to print_response/run
- Combine with search: Add search=True to get context about what's in the image

Example prompts to try:
- "Describe this image in detail"
- "What text can you see in this image?"
- "Tell me about this image and give me the latest news about it."
- "What architectural style is this building?"
"""

from agno.agent import Agent
from agno.media import Image
from agno.models.google import Gemini

# ---------------------------------------------------------------------------
# Agent Instructions
# ---------------------------------------------------------------------------
instructions = """\
You are an image analysis expert. Describe what you see in detail
and provide relevant context.

## Rules

- Describe the main subject first, then details
- Note any text visible in the image
- Provide historical or cultural context when relevant\
"""

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
image_agent = Agent(
    name="Image Analyst",
    # search=True lets the agent look up context about what it sees
    model=Gemini(id="gemini-3-flash-preview", search=True),
    instructions=instructions,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    image_agent.print_response(
        "Tell me about this image and give me the latest news about it.",
        images=[
            Image(
                url="https://agno-public.s3.amazonaws.com/images/krakow_mariacki.jpg"
            ),
        ],
        stream=True,
    )

# ---------------------------------------------------------------------------
# More Examples
# ---------------------------------------------------------------------------
"""
Image input methods:

1. From URL
   images=[Image(url="https://example.com/photo.jpg")]

2. From local file
   images=[Image(filepath="path/to/photo.jpg")]

3. Multiple images
   images=[Image(url="..."), Image(filepath="...")]

4. With structured output (extract data from images)
   class ImageData(BaseModel):
       objects: List[str]
       text_content: str
       mood: str

   agent = Agent(model=Gemini(...), output_schema=ImageData)
   result = agent.run("Analyze this image", images=[...])
   data: ImageData = result.content

Use cases for music/film/gaming:
- Analyze album artwork or movie posters
- Extract text from game screenshots
- Describe scene composition for storyboards
"""
