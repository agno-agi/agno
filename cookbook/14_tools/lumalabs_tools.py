from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.lumalab import LumaLabTools

"""Create an agent specialized for Luma AI video generation"""

luma_agent = Agent(
    name="Luma Video Agent",
    id="luma-video-agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[LumaLabTools()],  # Using the LumaLab tool we created
    markdown=True,
    instructions=[
        "You are an agent designed to generate videos using the Luma AI API.",
        "You can generate videos in two ways:",
        "1. Text-to-Video Generation:",
        "   - Use the generate_video function for creating videos from text prompts",
        "   - Default parameters: loop=False, aspect_ratio='16:9', keyframes=None",
        "2. Image-to-Video Generation:",
        "   - Use the image_to_video function when starting from one or two images",
        "   - Required parameters: prompt, start_image_url",
        "   - Optional parameters: end_image_url, loop=False, aspect_ratio='16:9'",
        "   - The image URLs must be publicly accessible",
        "Choose the appropriate function based on whether the user provides image URLs or just a text prompt.",
        "The video will be displayed in the UI automatically below your response, so you don't need to show the video URL in your response.",
        "Politely and courteously let the user know that the video has been generated and will be displayed below as soon as its ready.",
        "After generating any video, if generation is async (wait_for_completion=False), inform about the generation ID",
    ],
    system_message=(
        "Use generate_video for text-to-video requests and image_to_video for image-based "
        "generation. Don't modify default parameters unless specifically requested. "
        "Always provide clear feedback about the video generation status."
    ),
)

luma_agent.run("Generate a video of a car in a sky")
# luma_agent.run("Transform this image into a video of a tiger walking: https://upload.wikimedia.org/wikipedia/commons/thumb/3/3f/Walking_tiger_female.jpg/1920px-Walking_tiger_female.jpg")
# luma_agent.run("""
# Create a transition video between these two images:
# Start: https://img.freepik.com/premium-photo/car-driving-dark-forest-generative-ai_634053-6661.jpg?w=1380
# End: https://img.freepik.com/free-photo/front-view-black-luxury-sedan-road_114579-5030.jpg?t=st=1733821884~exp=1733825484~hmac=735ca584a9b985c53875fc1ad343c3fd394e1de4db49e5ab1a9ab37ac5f91a36&w=1380
# Make it a smooth, natural movement
# """)
