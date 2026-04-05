from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from agno.models.message import Message


class AgentRunException(Exception):
    def __init__(
        self,
        exc,
        user_message: Optional[Union[str, Message]] = None,
        agent_message: Optional[Union[str, Message]] = None,
        messages: Optional[List[Union[dict, Message]]] = None,
        stop_execution: bool = False,
    ):
        super().__init__(exc)
        self.user_message = user_message
        self.agent_message = agent_message
        self.messages = messages
        self.stop_execution = stop_execution
        self.type = "agent_run_error"
        self.error_id = "agent_run_error"


class RetryAgentRun(AgentRunException):
    """Exception raised when a tool call should be retried."""

    def __init__(
        self,
        exc,
        user_message: Optional[Union[str, Message]] = None,
        agent_message: Optional[Union[str, Message]] = None,
        messages: Optional[List[Union[dict, Message]]] = None,
    ):
        super().__init__(
            exc, user_message=user_message, agent_message=agent_message, messages=messages, stop_execution=False
        )
        self.error_id = "retry_agent_run_error"


class StopAgentRun(AgentRunException):
    """Exception raised when an agent should stop executing entirely."""

    def __init__(
        self,
        exc,
        user_message: Optional[Union[str, Message]] = None,
        agent_message: Optional[Union[str, Message]] = None,
        messages: Optional[List[Union[dict, Message]]] = None,
    ):
        super().__init__(
            exc, user_message=user_message, agent_message=agent_message, messages=messages, stop_execution=True
        )
        self.error_id = "stop_agent_run_error"


class RunCancelledException(Exception):
    """Exception raised when a run is cancelled."""

    def __init__(self, message: str = "Operation cancelled by user"):
        super().__init__(message)
        self.type = "run_cancelled_error"
        self.error_id = "run_cancelled_error"


class AgnoError(Exception):
    """Exception raised when an internal error occurs."""

    def __init__(self, message: str, status_code: int = 500):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.type = "agno_error"
        self.error_id = "agno_error"

    def __str__(self) -> str:
        return str(self.message)


class ModelAuthenticationError(AgnoError):
    """Raised when model authentication fails."""

    def __init__(self, message: str, status_code: int = 401, model_name: Optional[str] = None):
        super().__init__(message, status_code)
        self.model_name = model_name

        self.type = "model_authentication_error"
        self.error_id = "model_authentication_error"


class ModelProviderError(AgnoError):
    """Exception raised when a model provider returns an error."""

    # Patterns that indicate a context window / token limit exceeded error
    CONTEXT_WINDOW_PATTERNS = [
        "context_length_exceeded",
        "context window",
        "maximum context length",
        "token limit",
        "max_tokens",
        "too many tokens",
        "payload too large",
        "content_too_large",
        "request too large",
        "input too long",
        "exceeds the model",
    ]

    def __init__(
        self, message: str, status_code: int = 502, model_name: Optional[str] = None, model_id: Optional[str] = None
    ):
        super().__init__(message, status_code)
        self.model_name = model_name
        self.model_id = model_id

        self.type = "model_provider_error"
        self.error_id = "model_provider_error"

    @classmethod
    def classify(cls, error: "ModelProviderError") -> "ModelProviderError":
        """Re-classify a generic ModelProviderError into a specific subclass.

        If the error is already a specific subclass (ModelRateLimitError,
        ContextWindowExceededError), it is returned as-is. Otherwise, the
        error message and status code are inspected to determine if a more
        specific subclass applies.
        """
        # Already classified
        if isinstance(error, (ModelRateLimitError, ContextWindowExceededError)):
            return error

        # Rate-limit detection (429 standard, 529 Anthropic OverloadedError)
        if error.status_code in {429, 529}:
            return ModelRateLimitError(
                message=error.message,
                status_code=error.status_code,
                model_name=error.model_name,
                model_id=error.model_id,
            )

        # Context-window detection
        error_msg = str(error.message).lower()
        if any(pattern in error_msg for pattern in cls.CONTEXT_WINDOW_PATTERNS):
            return ContextWindowExceededError(
                message=error.message,
                status_code=error.status_code,
                model_name=error.model_name,
                model_id=error.model_id,
            )

        return error


class ModelRateLimitError(ModelProviderError):
    """Exception raised when a model provider returns a rate limit error."""

    def __init__(
        self, message: str, status_code: int = 429, model_name: Optional[str] = None, model_id: Optional[str] = None
    ):
        super().__init__(message, status_code, model_name, model_id)
        self.error_id = "model_rate_limit_error"


class ContextWindowExceededError(ModelProviderError):
    """Exception raised when the input exceeds a model's context window."""

    def __init__(
        self, message: str, status_code: int = 400, model_name: Optional[str] = None, model_id: Optional[str] = None
    ):
        super().__init__(message, status_code, model_name, model_id)
        self.error_id = "context_window_exceeded_error"


class EvalError(Exception):
    """Exception raised when an evaluation fails."""

    pass


class CheckTrigger(Enum):
    """Enum for guardrail triggers."""

    OFF_TOPIC = "off_topic"
    INPUT_NOT_ALLOWED = "input_not_allowed"
    OUTPUT_NOT_ALLOWED = "output_not_allowed"
    VALIDATION_FAILED = "validation_failed"

    PROMPT_INJECTION = "prompt_injection"
    PII_DETECTED = "pii_detected"


class InputCheckError(Exception):
    """Exception raised when an input check fails."""

    def __init__(
        self,
        message: str,
        check_trigger: CheckTrigger = CheckTrigger.INPUT_NOT_ALLOWED,
        additional_data: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.type = "input_check_error"
        if isinstance(check_trigger, CheckTrigger):
            self.error_id = check_trigger.value
        else:
            self.error_id = str(check_trigger)

        self.message = message
        self.check_trigger = check_trigger
        self.additional_data = additional_data


class OutputCheckError(Exception):
    """Exception raised when an output check fails."""

    def __init__(
        self,
        message: str,
        check_trigger: CheckTrigger = CheckTrigger.OUTPUT_NOT_ALLOWED,
        additional_data: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.type = "output_check_error"
        if isinstance(check_trigger, CheckTrigger):
            self.error_id = check_trigger.value
        else:
            self.error_id = str(check_trigger)

        self.message = message
        self.check_trigger = check_trigger
        self.additional_data = additional_data


@dataclass
class RetryableModelProviderError(Exception):
    original_error: Optional[str] = None
    # Guidance message to retry a model invocation after an error
    retry_guidance_message: Optional[str] = None


class RemoteServerUnavailableError(AgnoError):
    """Exception raised when a remote server is unavailable.

    This can happen due to:
    - Connection refused (server not running)
    - Connection timeout
    - Network errors
    - DNS resolution failures
    """

    def __init__(
        self,
        message: str,
        base_url: Optional[str] = None,
        original_error: Optional[Exception] = None,
    ):
        super().__init__(message, status_code=503)
        self.base_url = base_url
        self.original_error = original_error
        self.type = "remote_server_unavailable_error"
        self.error_id = "remote_server_unavailable_error"
