from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Optional
from uuid import uuid4

from agno.agents.base import BaseExternalAgent
from agno.agents.langgraph.utils import build_messages_with_history
from agno.models.response import ToolExecution
from agno.run.agent import (
    RunContentEvent,
    RunOutputEvent,
    ToolCallCompletedEvent,
    ToolCallStartedEvent,
)


@dataclass
class LangGraphAgent(BaseExternalAgent):
    """Adapter for LangGraph compiled graphs.

    Wraps a LangGraph compiled graph so it can be used with AgentOS endpoints
    or standalone via .run() / .print_response().

    Args:
        name: Display name for this agent.
        id: Unique identifier (auto-generated from name if not set).
        graph: A LangGraph compiled graph (from graph.compile()).
        input_key: Key in the graph state used for input messages. Defaults to "messages".
        output_key: Key in the graph state used for output messages. Defaults to "messages".
        config: Optional LangGraph config dict passed to invoke/stream calls.

    Example:
        from langgraph.graph import StateGraph, MessagesState
        from langchain_openai import ChatOpenAI
        from agno.agents.langgraph import LangGraphAgent

        def chatbot(state: MessagesState):
            return {"messages": [ChatOpenAI(model="gpt-5.4").invoke(state["messages"])]}

        graph = StateGraph(MessagesState)
        graph.add_node("chatbot", chatbot)
        graph.set_entry_point("chatbot")
        compiled = graph.compile()

        agent = LangGraphAgent(
            name="My LangGraph Agent",
            graph=compiled,
        )

        # Standalone usage
        agent.print_response("Hello!")

        # Or register with AgentOS
        from agno.os.app import AgentOS
        app = AgentOS(agents=[agent])
    """

    graph: Any = None
    input_key: str = "messages"
    output_key: str = "messages"
    config: Optional[Dict[str, Any]] = field(default=None)
    framework: str = "langgraph"

    async def _arun_adapter(
        self,
        input: Any,
        *,
        history: Optional[List[Dict[str, Any]]] = None,
        _lg_config_override: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Any:
        """Non-streaming LangGraph invocation."""
        try:
            from langchain_core.messages import AIMessage
        except ImportError:
            raise ImportError("langchain-core is required: pip install langchain-core langgraph")
        # None input means replay/fork from checkpoint
        if input is None:
            graph_input = None
        else:
            graph_input = {self.input_key: build_messages_with_history(input, history)}
        config = self._build_config(kwargs, override=_lg_config_override)

        result = await self.graph.ainvoke(graph_input, config=config)

        # Extract content from the last AI message
        messages = result.get(self.output_key, [])
        for msg in reversed(messages):
            if isinstance(msg, AIMessage):
                return msg.content
        return str(result)

    async def _arun_adapter_stream(
        self,
        input: Any,
        *,
        history: Optional[List[Dict[str, Any]]] = None,
        _lg_config_override: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> AsyncIterator[RunOutputEvent]:
        """Streaming LangGraph invocation with tool call visibility."""
        if self.graph is None:
            raise ValueError("No graph provided to LangGraphAgent")

        run_id = kwargs.get("run_id", str(uuid4()))
        # None input means replay/fork from checkpoint
        if input is None:
            graph_input = None
        else:
            graph_input = {self.input_key: build_messages_with_history(input, history)}
        config = self._build_config(kwargs, override=_lg_config_override)

        async for event in self.graph.astream_events(graph_input, config=config, version="v2"):
            kind = event.get("event")

            if kind == "on_chat_model_stream":
                chunk = event.get("data", {}).get("chunk")
                if chunk and hasattr(chunk, "content") and chunk.content:
                    # Only yield string content (skip tool call chunks)
                    if isinstance(chunk.content, str):
                        yield RunContentEvent(
                            run_id=run_id,
                            agent_id=self.get_id(),
                            agent_name=self.name or "",
                            content=chunk.content,
                        )

            elif kind == "on_tool_start":
                tool_name = event.get("name", "unknown")
                tool_input = event.get("data", {}).get("input", {})
                tool_run_id = event.get("run_id", str(uuid4()))
                yield ToolCallStartedEvent(
                    run_id=run_id,
                    agent_id=self.get_id(),
                    agent_name=self.name or "",
                    tool=ToolExecution(
                        tool_call_id=tool_run_id,
                        tool_name=tool_name,
                        tool_args=tool_input if isinstance(tool_input, dict) else {"input": tool_input},
                    ),
                )

            elif kind == "on_tool_end":
                tool_name = event.get("name", "unknown")
                output = event.get("data", {}).get("output", "")
                tool_run_id = event.get("run_id", str(uuid4()))
                result_str = str(output.content) if hasattr(output, "content") else str(output)
                yield ToolCallCompletedEvent(
                    run_id=run_id,
                    agent_id=self.get_id(),
                    agent_name=self.name or "",
                    tool=ToolExecution(
                        tool_call_id=tool_run_id,
                        tool_name=tool_name,
                        result=result_str,
                    ),
                )

    # ---------------------------------------------------------------------------
    # Time travel / state management (pass-through to LangGraph)
    # ---------------------------------------------------------------------------

    def get_state_history(self, session_id: str) -> List[Any]:
        """Get checkpoint history for a session (thread). Returns list of StateSnapshot objects.

        Requires the graph to be compiled with a checkpointer.
        """
        config = self._build_config({"session_id": session_id})
        return list(self.graph.get_state_history(config))

    def get_state(self, session_id: str) -> Any:
        """Get the current state for a session (thread). Returns a StateSnapshot.

        Requires the graph to be compiled with a checkpointer.
        """
        config = self._build_config({"session_id": session_id})
        return self.graph.get_state(config)

    def update_state(self, session_id: str, values: Dict[str, Any], as_node: Optional[str] = None) -> Any:
        """Update state at a checkpoint (fork). Returns the new config.

        Requires the graph to be compiled with a checkpointer.
        """
        config = self._build_config({"session_id": session_id})
        kwargs: Dict[str, Any] = {"values": values}
        if as_node:
            kwargs["as_node"] = as_node
        return self.graph.update_state(config, **kwargs)

    def replay(
        self,
        session_id: str,
        checkpoint_id: str,
        *,
        stream: bool = True,
        **kwargs: Any,
    ):
        """Replay from a specific checkpoint.

        Usage:
            history = agent.get_state_history("my-session")
            checkpoint = history[2]
            checkpoint_id = checkpoint.config["configurable"]["checkpoint_id"]
            agent.replay("my-session", checkpoint_id, stream=True)
        """
        replay_config = self._build_config({"session_id": session_id})
        replay_config["configurable"]["checkpoint_id"] = checkpoint_id

        # Pass config through kwargs; self.config stays untouched.
        return self.run(None, stream=stream, session_id=session_id, _lg_config_override=replay_config, **kwargs)

    def print_replay(
        self,
        session_id: str,
        checkpoint_id: str,
        *,
        stream: bool = True,
        **kwargs: Any,
    ) -> None:
        """Replay from a checkpoint and print the response with Rich formatting."""
        replay_config = self._build_config({"session_id": session_id})
        replay_config["configurable"]["checkpoint_id"] = checkpoint_id
        self.print_response(None, stream=stream, session_id=session_id, _lg_config_override=replay_config, **kwargs)

    def fork(
        self,
        session_id: str,
        checkpoint_id: str,
        values: Dict[str, Any],
        *,
        as_node: Optional[str] = None,
        stream: bool = True,
        **kwargs: Any,
    ):
        """Fork from a checkpoint with modified state, then continue execution.

        Usage:
            history = agent.get_state_history("my-session")
            checkpoint = history[2]
            checkpoint_id = checkpoint.config["configurable"]["checkpoint_id"]
            agent.fork("my-session", checkpoint_id, {"topic": "cats"}, stream=True)
        """
        fork_config_base = self._build_config({"session_id": session_id})
        fork_config_base["configurable"]["checkpoint_id"] = checkpoint_id

        update_kwargs: Dict[str, Any] = {"values": values}
        if as_node:
            update_kwargs["as_node"] = as_node
        new_config = self.graph.update_state(fork_config_base, **update_kwargs)

        # Pass config through kwargs; self.config stays untouched.
        return self.run(None, stream=stream, session_id=session_id, _lg_config_override=new_config, **kwargs)

    def print_fork(
        self,
        session_id: str,
        checkpoint_id: str,
        values: Dict[str, Any],
        *,
        as_node: Optional[str] = None,
        stream: bool = True,
        **kwargs: Any,
    ) -> None:
        """Fork from a checkpoint with modified state and print the response."""
        fork_config_base = self._build_config({"session_id": session_id})
        fork_config_base["configurable"]["checkpoint_id"] = checkpoint_id

        update_kwargs: Dict[str, Any] = {"values": values}
        if as_node:
            update_kwargs["as_node"] = as_node
        new_config = self.graph.update_state(fork_config_base, **update_kwargs)
        self.print_response(None, stream=stream, session_id=session_id, _lg_config_override=new_config, **kwargs)

    def _build_config(self, kwargs: Dict[str, Any], *, override: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Build a LangGraph config mapping session_id to thread_id."""
        # Shallow copy: configs commonly carry non-deepcopyable callbacks/tracers at the top level.
        base = override if override is not None else self.config
        config: Dict[str, Any] = dict(base or {})
        config["configurable"] = dict(config.get("configurable") or {})
        session_id = kwargs.get("session_id")
        if session_id:
            configurable = config["configurable"]
            configurable["thread_id"] = session_id
            configurable.setdefault("checkpoint_ns", "")
        return config
