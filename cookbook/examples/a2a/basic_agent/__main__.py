from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import (
    AgentAuthentication,
    AgentCapabilities,
    AgentCard,
    AgentSkill,
)
from basic_agent import BasicAgentExecutor

if __name__ == "__main__":
    skill = AgentSkill(
        id="agno_agent",
        name="Agno Agent",
        description="Agno Agent",
        tags=["Agno agent"],
        examples=["hi", "hello"],
    )

    agent_card = AgentCard(
        name="Agno Agent",
        description="Agno Agent",
        url="http://localhost:9999/",
        version="1.0.0",
        defaultInputModes=["text"],
        defaultOutputModes=["text"],
        capabilities=AgentCapabilities(),
        skills=[skill],
        authentication=AgentAuthentication(schemes=["public"]),
    )

    request_handler = DefaultRequestHandler(
        agent_executor=BasicAgentExecutor(),
        task_store=InMemoryTaskStore(),
    )

    server = A2AStarletteApplication(
        agent_card=agent_card, http_handler=request_handler
    )
    import uvicorn

    uvicorn.run(server.build(), host="0.0.0.0", port=9999, timeout_keep_alive=10)
