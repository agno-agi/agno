import json
from textwrap import dedent
from typing import Any, AsyncIterator, List, Optional, Union
from uuid import uuid4

from agno.agent import Agent
from agno.db.base import AsyncBaseDb, BaseDb
from agno.models.base import Model
from agno.run.agent import RunContentEvent, RunOutputEvent, run_output_event_from_dict
from agno.run.base import RunContext
from agno.tools.function import Function
from agno.tools.toolkit import Toolkit
from agno.utils.log import log_debug, log_error


def _event_from_sse(sse_data: Any) -> Optional[Any]:
    """Parse an SSE-formatted string from a background stream back into a run event.

    Background streaming runs yield "event: <type>\\ndata: <json>\\n\\n" strings
    (their static type says events, but the background path serializes). Returns
    None for chunks that cannot be parsed; the caller skips them.
    """
    if not isinstance(sse_data, str):
        return None
    try:
        for line in sse_data.split("\n"):
            if line.startswith("data: "):
                return run_output_event_from_dict(json.loads(line[len("data: ") :]))
    except Exception:
        log_debug("Could not parse SSE event from subagent background stream")
    return None


DEFAULT_INSTRUCTIONS = dedent("""\
    You can delegate tasks to subagents: isolated copies of yourself with a fresh
    context that work on a task and return the result. Use them to parallelize
    independent work and to keep noisy side-work out of this conversation.
    - Call spawn_agent once per independent sub-task. Call it multiple times in the
      same response to run subagents in parallel; total time equals the largest task,
      not the sum.
    - Only spawn when it pays off: several independent pieces, or one large
      self-contained chunk of research or grunt work. Do small tasks, follow-up
      questions and sequential work (where each step needs the previous step's
      result) yourself - spawning costs more than doing it.
    - Keep each task small and atomic: one topic, component, or question per subagent.
      Never give one subagent a numbered list of independent items - split the list
      into one spawn_agent call per item. Never give two subagents overlapping work.
    - Subagents start fresh and do not see this conversation. Every brief must be
      self-contained - full context, precise scope, and the exact output to return
      (a summary, a list of findings with sources - never raw dumps).
    - Keep the hardest parts of the work for yourself and combine the subagent results
      into your final answer.""")


class SubAgent(Toolkit):
    """Let an agent spin up subagents (copies of itself) to get tasks done in parallel.

    Subagents inherit the parent agent's model, tools and db by default; each can be
    overridden via the constructor. Every spawn_agent call runs in its own
    "<parent id>-subagent-task-<uuid>" session with the user_id inherited from the
    current run (falling back to the parent agent's id when the run has no user), so
    subagent runs can be inspected as separate sessions in the db / AgentOS UI.

    When a db is set, subagent runs execute as detached background runs on the server
    (the same pipeline as AgentOS "Run in background"), so they survive client
    disconnects and page refreshes. Their events are also re-emitted into the parent
    run's stream tagged with parent_run_id, so each spawn_agent call renders as nested
    sub-agent activity inside the parent's chat in the AgentOS UI (same as team member
    delegation) while still persisting as its own session. Note the parent run is
    controlled separately: to keep the whole tree alive across a refresh, start the
    parent run in background mode too (the "Run in background" toggle in the AgentOS
    UI).

    Args:
        model: Model for subagents. Defaults to the parent agent's model.
        tools: Tools for subagents. Defaults to the parent agent's tools, excluding any
            SubAgent instances (subagents cannot spawn their own subagents).
        db: Database for subagent sessions. Defaults to the parent agent's db.
    """

    def __init__(
        self,
        model: Optional[Model] = None,
        tools: Optional[List[Any]] = None,
        db: Optional[Union[BaseDb, AsyncBaseDb]] = None,
        **kwargs,
    ):
        self.model = model
        self.subagent_tools = tools
        self.db = db
        self._subagent: Optional[Agent] = None

        super().__init__(
            name="subagent",
            tools=[self.spawn_agent],
            instructions=kwargs.pop("instructions", DEFAULT_INSTRUCTIONS),
            add_instructions=kwargs.pop("add_instructions", True),
            **kwargs,
        )
        # Toolkit.register auto-detects async via iscoroutinefunction, which does not
        # recognize async generator functions - register the async variant directly so
        # it lands in async_functions instead of overwriting the sync tool.
        self.async_functions["spawn_agent"] = Function(name="spawn_agent", entrypoint=self.aspawn_agent)

    def _get_subagent(self, parent: Agent) -> Agent:
        """Build the subagent once and reuse it. Session and user ids are passed per run,
        so a single instance safely serves parallel run_task calls."""
        if self._subagent is not None:
            return self._subagent

        tools = self.subagent_tools
        if tools is None and isinstance(parent.tools, list):
            # Subagents must not spawn subagents of their own
            tools = [t for t in parent.tools if not isinstance(t, SubAgent)]

        self._subagent = Agent(
            id=parent.id,
            name=f"{parent.name}" if parent.name else "Subagent",
            model=self.model if self.model is not None else parent.model,
            tools=tools,
            debug_mode=parent.debug_mode,
            store_events=parent.store_events,
            db=self.db if self.db is not None else parent.db,
        )
        return self._subagent

    def _session_id(self, parent: Agent) -> str:
        return f"{parent.id}-subagent-task-{uuid4()}"

    def spawn_agent(self, agent: Agent, run_context: RunContext, task: str) -> str:
        """Delegate a task to a subagent and return its result.

        Args:
            task (str): Complete, self-contained task description. The subagent does not
                see this conversation, so include all context it needs.

        Returns:
            str: The subagent's response.
        """
        try:
            subagent = self._get_subagent(agent)
            session_id = self._session_id(agent)
            user_id = run_context.user_id or agent.id
            log_debug(f"Running subagent task in session {session_id}")
            result = subagent.run(task, user_id=user_id, session_id=session_id)
            return result.get_content_as_string()
        except Exception as e:
            log_error(f"Subagent task failed: {e}")
            return f"Subagent task failed: {str(e)}"

    async def aspawn_agent(
        self, agent: Agent, run_context: RunContext, task: str
    ) -> AsyncIterator[Union[RunOutputEvent, str]]:
        """Delegate a task to a subagent and return its result. Call spawn_agent multiple
        times in the same response to run subagents in parallel.

        Args:
            task (str): Complete, self-contained task description. The subagent does not
                see this conversation, so include all context it needs.

        Returns:
            str: The subagent's response.
        """
        try:
            subagent = self._get_subagent(agent)
            session_id = self._session_id(agent)
            user_id = run_context.user_id or agent.id
            log_debug(f"Running subagent task in session {session_id}")
            if subagent.db is not None:
                # Background streaming run: the RUNNING run is persisted to the db
                # immediately and every event is pushed to the AgentOS event buffer,
                # so the subagent session can be watched live in the UI exactly like
                # a main agent run. The stream ends when the run completes.
                # Each SSE chunk is also parsed back into a run event, tagged with
                # the parent run's id and yielded upward, so the subagent renders
                # nested inside the parent run in the AgentOS UI (same mechanism as
                # team member delegation). Content events are accumulated into the
                # tool result by the model layer, so no final string is yielded
                # unless nothing was streamed.
                run_id = str(uuid4())
                streamed_content = False
                async for sse_data in subagent.arun(
                    task,
                    user_id=user_id,
                    session_id=session_id,
                    run_id=run_id,
                    background=True,
                    stream=True,
                    stream_events=True,
                ):
                    event = _event_from_sse(sse_data)
                    if event is None:
                        continue
                    event.parent_run_id = getattr(event, "parent_run_id", None) or run_context.run_id
                    # Re-emitted copies must belong to the session the client is
                    # watching (same as team members and context-provider
                    # sub-agents), otherwise the UI drops them. The subagent's own
                    # run still persists under its separate session.
                    if run_context.session_id:
                        event.session_id = run_context.session_id
                    if isinstance(event, RunContentEvent) and event.content:
                        streamed_content = True
                    yield event
                result = await subagent.aget_run_output(run_id=run_id, session_id=session_id, user_id=user_id)
                if result is None:
                    if not streamed_content:
                        yield "Subagent task finished but no output was stored."
                    return
                status = getattr(result, "status", None)
                if (getattr(status, "value", status)) == "ERROR":
                    yield f"Subagent task failed: {result.get_content_as_string() or 'run ended with status ERROR'}"
                    return
                if not streamed_content:
                    # No content events made it through the stream; fall back to the
                    # persisted output so the tool result is never empty.
                    yield result.get_content_as_string()
                return
            result = await subagent.arun(task, user_id=user_id, session_id=session_id)
            yield result.get_content_as_string()
        except Exception as e:
            log_error(f"Subagent task failed: {e}")
            yield f"Subagent task failed: {str(e)}"
