from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.types import Part, TextPart
from a2a.utils import new_agent_text_message
from agno.agent import Agent, Message, RunOutput
from agno.models.openai import OpenAIChat
from typing_extensions import override

agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
)


class BasicAgentExecutor(AgentExecutor):
    """Test AgentProxy Implementation."""

    def __init__(self):
        self.agent = agent

    @override
    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        message: Message = Message(role="user", content="")
        for part in context.message.parts:
            if isinstance(part, Part):
                if isinstance(part.root, TextPart):
                    message.content = part.root.text
                    break

        result: RunOutput = await self.agent.arun(message)
        event_queue.enqueue_event(new_agent_text_message(result.content))

    @override
    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise Exception("Cancel not supported")
