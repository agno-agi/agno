from agno.agent import Agent
from agno.media import Image
from agno.models.groq import Groq

agent = Agent(model=Groq(id="llama-3.2-90b-vision-preview"))

agent.print_response(
    "Tell me about this image",
    images=[
        Image(
            url="https://upload.wikimedia.org/wikipedia/commons/b/bf/Krakow_-_Kosciol_Mariacki.jpg"
        ),
    ],
    stream=True,
)
