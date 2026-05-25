from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Optional
from uuid import uuid4

from agno.agents.base import BaseExternalAgent
from agno.agents.dspy.utils import build_input_with_history
from agno.models.response import ToolExecution
from agno.run.agent import (
    RunContentEvent,
    RunOutputEvent,
    ToolCallCompletedEvent,
    ToolCallStartedEvent,
)


@dataclass
class DSPyAgent(BaseExternalAgent):
    """Adapter for DSPy modules and programs.

    Wraps any DSPy Module (Predict, ChainOfThought, ReAct, or custom) so it can
    be used with AgentOS endpoints or standalone via .run() / .print_response().

    Args:
        name: Display name for this agent.
        id: Unique identifier (auto-generated from name if not set).
        program: A DSPy Module instance (e.g. dspy.Predict, dspy.ChainOfThought, dspy.ReAct, or custom).
        input_field: Name of the input field in the DSPy signature. Defaults to "question".
        output_field: Name of the output field to extract from the Prediction. Defaults to "answer".
        lm: Optional DSPy LM instance to configure before running. If not provided, uses dspy global config.
        program_kwargs: Additional kwargs passed to the program on every call.

    Example:
        import dspy
        from agno.agents.dspy import DSPyAgent

        dspy.configure(lm=dspy.LM("openai/gpt-5.4"))

        agent = DSPyAgent(
            name="DSPy Q&A",
            program=dspy.ChainOfThought("question -> answer"),
        )

        # Standalone usage
        agent.print_response("What is quantum computing?")

        # Or deploy with AgentOS
        from agno.os.app import AgentOS
        AgentOS(agents=[agent])
    """

    program: Any = None
    input_field: str = "question"
    output_field: str = "answer"
    lm: Any = None
    program_kwargs: Dict[str, Any] = field(default_factory=dict)
    framework: str = "dspy"

    @staticmethod
    def _clone_lm_without_cache(lm: Any) -> Any:
        """Clone `lm` with caching disabled.

        Prefers `dspy.LM.copy(**overrides)` — the idiomatic path — which deep-copies
        and preserves num_retries, callbacks, launch_kwargs, and other top-level LM
        attributes that aren't in `lm.kwargs`. Falls back to rebuilding from `lm.kwargs`
        for custom LM subclasses that don't implement copy().
        """
        copy_fn = getattr(lm, "copy", None)
        if callable(copy_fn):
            return copy_fn(cache=False)

        import dspy

        preserved = {k: v for k, v in (getattr(lm, "kwargs", {}) or {}).items() if v is not None}
        preserved["cache"] = False
        model_type = getattr(lm, "model_type", None)
        if model_type is not None:
            preserved.setdefault("model_type", model_type)
        return dspy.LM(lm.model, **preserved)

    async def _arun_adapter(self, input: Any, *, history: Optional[List[Dict[str, Any]]] = None, **kwargs: Any) -> str:
        """Non-streaming: run the DSPy program and return the output field."""
        try:
            import dspy
        except ImportError:
            raise ImportError("dspy is required: pip install dspy")

        if self.program is None:
            raise ValueError("No program provided to DSPyAgent")

        # Build input kwargs with history prepended
        program_input = {self.input_field: build_input_with_history(input, history)}
        program_input.update(self.program_kwargs)

        # DSPy modules are sync by default — use asyncify
        async_program = dspy.asyncify(self.program)

        # Use dspy.context for thread-safe LM scoping
        if self.lm is not None:
            with dspy.context(lm=self.lm):
                result = await async_program(**program_input)
        else:
            result = await async_program(**program_input)

        # Extract the output field from the Prediction
        output = getattr(result, self.output_field, None)
        if output is None:
            # Fall back to string representation of the whole prediction
            return str(result)
        return str(output)

    async def _arun_adapter_stream(
        self, input: Any, *, history: Optional[List[Dict[str, Any]]] = None, **kwargs: Any
    ) -> AsyncIterator[RunOutputEvent]:
        """Streaming: use dspy.streamify() for token-level streaming.

        dspy.streamify() yields three types:
        - dspy.streaming.StreamResponse: token chunks (has .chunk, .predict_name, .signature_field_name)
        - dspy.Prediction: final program output
        - dspy.streaming.StatusMessage: execution status updates
        """
        try:
            import dspy
            import dspy.streaming
        except ImportError:
            raise ImportError("dspy is required: pip install dspy")

        if self.program is None:
            raise ValueError("No program provided to DSPyAgent")

        run_id = kwargs.get("run_id", str(uuid4()))

        # Build input kwargs with history prepended
        program_input = {self.input_field: build_input_with_history(input, history)}
        program_input.update(self.program_kwargs)

        # DSPy caches LLM responses by default. Cached results skip token-level
        # streaming and yield only the final Prediction. To get real streaming,
        # we temporarily scope a non-cached LM via dspy.context().
        current_lm = self.lm or dspy.settings.lm
        if current_lm and getattr(current_lm, "cache", True):
            stream_lm = self._clone_lm_without_cache(current_lm)
        else:
            stream_lm = current_lm

        # Configure stream_listeners to stream the output field
        streaming_program = dspy.streamify(
            self.program,
            stream_listeners=[dspy.streaming.StreamListener(signature_field_name=self.output_field)],
        )

        # DSPy emits StreamResponse chunks first and Prediction last, so tool events land after text.
        with dspy.context(lm=stream_lm):
            async for chunk in streaming_program(**program_input):
                if isinstance(chunk, dspy.streaming.StreamResponse):
                    if chunk.chunk:
                        yield RunContentEvent(
                            run_id=run_id,
                            agent_id=self.get_id(),
                            agent_name=self.name or "",
                            content=chunk.chunk,
                        )

                elif isinstance(chunk, dspy.Prediction):
                    trajectory = getattr(chunk, "trajectory", {}) or {}
                    i = 0
                    while f"tool_name_{i}" in trajectory:
                        t_name = trajectory[f"tool_name_{i}"]
                        t_args = trajectory.get(f"tool_args_{i}", {})
                        t_result = trajectory.get(f"observation_{i}", "")
                        if t_name != "finish":
                            t_id = str(uuid4())
                            yield ToolCallStartedEvent(
                                run_id=run_id,
                                agent_id=self.get_id(),
                                agent_name=self.name or "",
                                tool=ToolExecution(
                                    tool_call_id=t_id,
                                    tool_name=str(t_name),
                                    tool_args=t_args if isinstance(t_args, dict) else {"input": str(t_args)},
                                ),
                            )
                            yield ToolCallCompletedEvent(
                                run_id=run_id,
                                agent_id=self.get_id(),
                                agent_name=self.name or "",
                                tool=ToolExecution(
                                    tool_call_id=t_id,
                                    tool_name=str(t_name),
                                    result=str(t_result),
                                ),
                            )
                        i += 1

                # StatusMessage — skip (internal DSPy execution status)
