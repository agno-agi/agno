"""
Workflow via AG-UI
==================

Exposes an Agno Workflow through the AG-UI interface and exercises BOTH of the
completion gate's paths:

- Small talk routes to a non-streaming FUNCTION step (`chat_reply`). Its output
  lands only in WorkflowCompletedEvent.content, so the gate emits it as the
  final answer (the "non-streamed final" path).
- Substantive questions route to research + summarize AGENT steps, whose text
  streams live; the gate skips re-emitting the already-streamed final answer
  (the "streamed final / no recap" path).

A keyword-based Router picks the branch. Mirrors the selector pattern in
cookbook/04_workflows/05_conditional_branching/router_basic.py.

Run:
    .venvs/demo/bin/python cookbook/05_agent_os/interfaces/agui/workflow.py
then point an AG-UI client (e.g. Dojo) at http://localhost:9001/agui.
"""

from typing import List

from agno.agent.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.interfaces.agui import AGUI
from agno.workflow.router import Router
from agno.workflow.step import Step
from agno.workflow.types import StepInput, StepOutput
from agno.workflow.workflow import Workflow

researcher = Agent(
    name="Researcher",
    model=OpenAIResponses(id="gpt-5.5"),
    instructions="Research the topic and return three key facts as bullets.",
    markdown=True,
)

summarizer = Agent(
    name="Summarizer",
    model=OpenAIResponses(id="gpt-5.5"),
    instructions="Summarize the input into a single paragraph.",
    markdown=True,
)


def chat_reply(step_input: StepInput) -> StepOutput:
    """Quick deterministic small-talk reply. As a function step (no agent) its
    output is not streamed — it lands only in WorkflowCompletedEvent.content,
    exercising the completion gate's non-streamed-final path."""
    return StepOutput(content="Hi! Ask me a question and I'll research it for you.")


chat_step = Step(name="chat", executor=chat_reply)
research_step = Step(name="research", agent=researcher)
summarize_step = Step(name="summarize", agent=summarizer)


def chat_vs_research_router(step_input: StepInput) -> List[Step]:
    """Route small talk to the quick function reply; everything else to research+summarize."""
    text = (step_input.input or "").lower().strip()
    chat_signals = {
        "hi",
        "hello",
        "hey",
        "thanks",
        "thank you",
        "yo",
        "good morning",
        "good evening",
        "good afternoon",
    }
    if text in chat_signals or len(text.split()) <= 2:
        return [chat_step]
    return [research_step, summarize_step]


adaptive_workflow = Workflow(
    name="Adaptive Workflow",
    description="Greet small talk directly; research and summarize for substantive questions.",
    steps=[
        Router(
            name="chat_or_research_router",
            selector=chat_vs_research_router,
            choices=[chat_step, research_step, summarize_step],
            description="Pick a quick chat reply for small talk, otherwise research+summarize.",
        ),
    ],
)

agent_os = AgentOS(
    workflows=[adaptive_workflow],
    interfaces=[AGUI(workflow=adaptive_workflow)],
)
app = agent_os.get_app()


if __name__ == "__main__":
    agent_os.serve(app="workflow:app", reload=True, port=9001)
