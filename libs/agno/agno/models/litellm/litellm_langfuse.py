from typing import Any, Dict

from agno.models.litellm.chat import LiteLLM

try:
    from langfuse.decorators import langfuse_context
except ImportError:
    raise ImportError("`langfuse` not installed. Please install it via `pip install langfuse`")


class LiteLLMLangfuse(LiteLLM):
    def __post_init__(self):
        super.__post_init__()

        import litellm

        litellm.success_callback.append('langfuse')
        litellm.failure_callback.append('langfuse')


    @property
    def request_kwargs(self) -> Dict[str, Any]:
        """Get the request kwargs for the LiteLLM API."""
        completion_kwargs = super().request_kwargs
        existed_trace_id = langfuse_context.get_current_trace_id()
        if existed_trace_id:
            completion_kwargs["metadata"] = completion_kwargs.get("metadata", {})
            completion_kwargs["metadata"]["existing_trace_id"] = existed_trace_id
        return completion_kwargs
