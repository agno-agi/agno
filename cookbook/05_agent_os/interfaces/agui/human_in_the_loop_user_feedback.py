"""Human in the Loop over AG-UI - User Feedback (multiple choice)
================================================================

An agent that uses ``UserFeedbackTools`` (the ``ask_user`` tool) to pause and ask the
human to choose from a set of options before continuing. This is the "agent asks the
human to decide" case - distinct from confirmation (approve/reject a tool) and from
user_input (fill in free-form fields).

Over AG-UI the pause surfaces as a ``TOOL_CALL_*`` for ``ask_user`` whose args carry the
questions and their options; the client renders the choices and returns the answer as a
``ToolMessage`` whose content is the JSON string::

    {"selections": {"<question text>": ["<chosen label>", ...]}}

The AG-UI interface resolves that back into the paused run via
``RunRequirement.provide_user_feedback(...)`` and continues server-side. Each key is the
exact question string the agent sent (echoed from the tool-call args); each value is a
list of chosen option labels (a single-element list for a single-select question).

Run::

    OPENAI_API_KEY=... python cookbook/05_agent_os/interfaces/agui/human_in_the_loop_user_feedback.py

Then drive it from an AG-UI client (or curl): ask e.g. "help me pick a cuisine for
dinner"; the agent calls ``ask_user`` with a few options and pauses; reply with a
ToolMessage ``{"selections": {"<question>": ["<label>"]}}`` and the agent continues with
your choice.
"""

from agno.agent.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.interfaces.agui import AGUI
from agno.tools.user_feedback import UserFeedbackTools

hitl_feedback_agent = Agent(
    name="human_in_the_loop_feedback",
    model=OpenAIResponses(id="gpt-5.5"),
    db=SqliteDb(db_file="/tmp/agui_hitl_user_feedback.db"),
    tools=[UserFeedbackTools()],
    instructions=(
        "You help the user make decisions. When a choice would benefit from the user's "
        "input, call the ask_user tool with a clear question and 2-4 concise options "
        "instead of guessing. Wait for the user's selection, then continue using exactly "
        "what they picked and briefly confirm the chosen option in your final answer."
    ),
    add_history_to_context=True,
    markdown=True,
)

agent_os = AgentOS(
    agents=[hitl_feedback_agent],
    interfaces=[AGUI(agent=hitl_feedback_agent, prefix="/human_in_the_loop_feedback")],
)
app = agent_os.get_app()


if __name__ == "__main__":
    agent_os.serve(app=app, host="127.0.0.1", port=9001)
