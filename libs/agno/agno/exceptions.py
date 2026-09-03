import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from agno.models.message import Message

# Credential shapes that provider error messages sometimes echo back. Applied to text
# that gets persisted or served over an API, where it reaches a wider audience than logs.
_SECRET_PATTERNS = [
    # Key-shaped tokens. Asterisks and bullets are included because some providers
    # echo a partially masked key, which should still be normalised to [redacted].
    # Prefixes that are followed by a separator (sk-..., xoxb-...).
    re.compile(r"\b(?:sk|pk|rk|ghp|gho|xoxb|xoxp|pa)[-_][A-Za-z0-9\-_*•]{8,}", re.IGNORECASE),
    # Prefixes that run straight into the key body: Google (AIzaSy...), HuggingFace (hf_...),
    # Jina (jina_...) and AWS access key ids (AKIA/ASIA + 16 uppercase alphanumerics).
    re.compile(r"\bAIza[A-Za-z0-9\-_*•]{10,}"),
    re.compile(r"\b(?:hf|jina)_[A-Za-z0-9\-_*•]{8,}", re.IGNORECASE),
    re.compile(r"\b(?:AKIA|ASIA|AGPA|AIDA|AROA|AIPA|ANPA|ANVA)[A-Z0-9]{12,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9\-._~+/]{8,}=*", re.IGNORECASE),
    re.compile(r"\b(api[-_]?key|access[-_]?token|secret)\s*[=:]\s*\S+", re.IGNORECASE),
    # Long hex runs only when labelled as a credential: bare 32-char hex is also the
    # shape of md5 content hashes and chunk ids, which are useful diagnostics.
    re.compile(
        r"\b(?:token|secret|key|password|signature|credential)\b[^A-Za-z0-9]{0,3}[A-Fa-f0-9]{32,}\b",
        re.IGNORECASE,
    ),
]

# Credentials embedded in a URL (scheme://user:secret@host). Kept apart from
# ``_SECRET_PATTERNS`` because only the password is replaced, not the whole match.
_URL_CREDENTIAL_PATTERN = re.compile(r"([A-Za-z][A-Za-z0-9+.\-]*://[^\s:/@]+):[^\s@]+@")


def redact_secrets(text: str) -> str:
    """Replace credential-like fragments in ``text`` with ``[redacted]``."""
    text = _URL_CREDENTIAL_PATTERN.sub(r"\1:[redacted]@", text)
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(
            lambda m: f"{m.group(1)}=[redacted]" if m.re.groups and m.group(1) else "[redacted]",
            text,
        )
    return text


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
        "prompt is too long",
        "prompt too long",
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


class EmbeddingError(AgnoError):
    """Raised when an embedder fails to produce an embedding.

    Embedding failures must never be silent: a chunk that fails to embed is a
    chunk the agent can never retrieve, so returning an empty vector would let
    ingestion report success while the content is unsearchable.
    """

    # Substrings that identify the underlying cause, checked against the provider's message
    _AUTH_PATTERNS = [
        "api key",
        "api_key",
        "unauthorized",
        "authentication",
        "invalid_api_key",
        "permission denied",
        "forbidden",
    ]
    _RATE_LIMIT_PATTERNS = [
        "rate limit",
        "rate_limit",
        "too many requests",
        "quota",
        "429",
    ]
    _TOO_LARGE_PATTERNS = [
        "maximum context length",
        "too long",
        "too large",
        "exceeds",
        "max_tokens",
        "token limit",
    ]

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        model_id: Optional[str] = None,
        provider: Optional[str] = None,
    ):
        # ``status_code`` is None when the provider reported no HTTP status. The attribute
        # still exposes 502 so the API surface always has a code, but classification keys
        # off ``provider_status_code`` so a synthesized default never outranks the message.
        self.provider_status_code = status_code
        super().__init__(message, status_code if status_code is not None else 502)
        self.model_id = model_id
        self.provider = provider

        self.type = "embedding_error"
        self.error_id = "embedding_error"

    @property
    def reason(self) -> str:
        """Best-effort category of the failure, for user-facing recovery hints.

        One of: ``authentication``, ``rate_limit``, ``content_too_large``, ``unknown``.
        """
        message = str(self.message).lower()

        # A status code the provider actually reported outranks the message text. Providers
        # routinely name the credential in a throttling message ("rate limit exceeded for
        # your api key"), and matching that text first would report a retryable 429 as a
        # permanent auth failure. A synthesized default is not the provider's word, so it
        # is left out of this check and classification falls through to the text below.
        status_code = self.provider_status_code
        if status_code == 429:
            return "rate_limit"
        if status_code in {401, 403}:
            return "authentication"
        # A server-side fault is transient regardless of what the body happens to mention.
        if status_code is not None and 500 <= status_code < 600:
            return "unknown"

        if any(p in message for p in self._RATE_LIMIT_PATTERNS):
            return "rate_limit"
        if any(p in message for p in self._AUTH_PATTERNS):
            return "authentication"
        if any(p in message for p in self._TOO_LARGE_PATTERNS):
            return "content_too_large"
        return "unknown"

    @property
    def recovery_hint(self) -> str:
        """A short, actionable next step for the user, derived from ``reason``."""
        return {
            "authentication": "Check the embedder's API key and permissions.",
            "rate_limit": "The embedding provider rate-limited this request; "
            "wait for the limit to reset, or lower the embedder batch size.",
            "content_too_large": "One or more chunks exceed the embedder's input limit; reduce the chunk size.",
            "unknown": "If the failure persists, check the embedder configuration.",
        }[self.reason]

    @property
    def is_retryable(self) -> bool:
        """Whether re-sending the same request could plausibly succeed.

        Authentication and oversized-input failures are deterministic: the same credential
        is rejected, and the same chunk is too large, on every attempt, so retrying only
        delays the report. Every other category may be transient, and losing a chunk costs
        more than a wasted attempt.
        """
        return self.reason not in ("authentication", "content_too_large")

    @property
    def safe_message(self) -> str:
        """The provider's message with credential-like fragments removed.

        This message is persisted to the contents database and returned by the
        knowledge API, so it reaches a wider audience than the process logs.
        """
        return redact_secrets(str(self.message))


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


class PathSecurityError(AgnoError):
    """Exception raised when path validation rejects user-supplied input."""

    def __init__(self, message: str = "Path security violation"):
        super().__init__(message, status_code=400)
        self.type = "path_security_error"
        self.error_id = "path_security_error"


class ComponentRehydrationError(AgnoError):
    """Raised when a persisted component cannot be fully reconstructed.

    A serialized agent, team or workflow references objects that live outside
    its config (tools, schemas, knowledge, dbs, member components). When such
    a reference cannot be resolved from the provided registry or database, the
    component would silently run with less than what was saved - no tools,
    missing members, no persistence. Deserialization raises this error instead,
    when the caller asks for strict reconstruction with ``strict=True``.
    """

    def __init__(self, message: str):
        super().__init__(message, status_code=422)
        self.type = "component_rehydration_error"
        self.error_id = "component_rehydration_error"


class ComponentPinError(ComponentRehydrationError):
    """Raised when an explicitly pinned component version cannot be satisfied.

    A parent component's links pin a child at an exact stored version. When
    that version is missing or fails to rebuild, the refusal names the pin and
    the remedy (re-save the parent), which no broader guard can improve on.
    """


class SchemaMismatchError(AgnoError):
    """Raised when an existing database table does not match the schema this version of Agno expects.

    Base class for schema validation failures. ``MigrationRequiredError`` is raised for
    table types that ``MigrationManager`` can migrate; this class is raised for the rest,
    where the table was likely created or modified outside Agno and needs repair rather
    than a migration. Build instances with ``agno.db.utils.table_schema_mismatch_error``
    so the message names the right remedy.

    Surfaces over HTTP as a 500 whose body carries ``error_id``, so clients can tell it
    apart from other server errors without parsing the message.
    """

    def __init__(self, table_name: str, message: Optional[str] = None):
        if message is None:
            message = f"Table {table_name} has an invalid schema: it does not match what this version of Agno expects."
        super().__init__(message, status_code=500)
        self.table_name = table_name
        self.type = "schema_mismatch_error"
        self.error_id = "schema_mismatch_error"


class MigrationRequiredError(SchemaMismatchError):
    """Raised when a table's schema is stale and a pending Agno migration can fix it.

    The usual cause is a database created by an older version of Agno whose migrations
    have not been applied yet. Run them from code with
    ``asyncio.run(MigrationManager(db).up())`` (``agno.db.migrations.manager``) or over
    HTTP with ``POST /databases/all/migrate`` on AgentOS.

    Carries ``error_id="migration_required_error"`` so a client can offer the migration.
    """

    def __init__(self, table_name: str, message: Optional[str] = None):
        if message is None:
            message = (
                f"Table {table_name} has an invalid schema: it does not match what this version of Agno "
                "expects. If this database was created by an older version of Agno, apply the pending "
                "migrations with `asyncio.run(MigrationManager(db).up())` (import it from "
                "`agno.db.migrations.manager`) or via the AgentOS endpoint `POST /databases/all/migrate`."
            )
        super().__init__(table_name, message)
        self.type = "migration_required_error"
        self.error_id = "migration_required_error"


class RunNotFoundError(RuntimeError):
    """Raised when a run_id cannot be found in the session.

    Subclasses ``RuntimeError`` so existing SDK callers that catch ``RuntimeError``
    keep working; the OS layer maps it to HTTP 404.
    """


class RunNotContinuableError(ValueError):
    """Raised when a run cannot be continued from its current state (e.g. cancelled).

    Subclasses ``ValueError`` so existing SDK callers that catch ``ValueError``
    keep working; the OS layer maps it to HTTP 409.
    """
