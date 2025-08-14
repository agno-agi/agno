from agno.agent import Agent
from agno.models.google import Gemini
from agno.os.app import AgentOS
from agno.os.interfaces.whatsapp.whatsapp import Whatsapp

image_agent = Agent(
    model=Gemini(
        id="gemini-2.0-flash-exp-image-generation",
        response_modalities=["Text", "Image"],
    ),
    debug_mode=True,
)

# Setup our AgentOS app
agent_os = AgentOS(
    description="AgentOS setup with a Whatsapp interface",
    agents=[image_agent],
    interfaces=[Whatsapp(agent=image_agent)],
)

app = agent_os.get_app()


if __name__ == "__main__":
    """Run our AgentOS.

    You can see the configuration and available interfaces on:
    http://localhost:7777/config

    """
    agent_os.serve(app="image_generation_model:app", reload=True)
