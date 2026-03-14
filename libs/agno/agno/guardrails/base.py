from typing import Any, Callable, Dict, Optional, Union

from agno.run.agent import RunInput, RunOutput
from agno.run.messages import RunMessages
from agno.run.team import TeamRunInput, TeamRunOutput
from agno.utils.log import log_warning

# Callback type for guardrail failures: (error, input_data, context) -> None
OnFailCallback = Callable[[Exception, Any, Dict[str, Any]], None]


class BaseGuardrail:
    """Base class for all guardrail implementations."""

    def __init__(self, dry_run: bool = False, on_fail: Optional[OnFailCallback] = None):
        """Initialize a new BaseGuardrail.

        Args:
            dry_run: If True, logs violations without raising errors.
            on_fail: Optional callback invoked when a check fails.
                     Receives (error, input_data, context) where context includes
                     guardrail_name, check_type, and additional_info.
        """
        self.dry_run = dry_run
        self.on_fail = on_fail

    def _handle_violation(
        self,
        error: Exception,
        guardrail_name: str,
        check_type: str,
        additional_info: Optional[str] = None,
        input_data: Any = None,
    ) -> None:
        """Handle a guardrail violation by invoking on_fail and then raising or logging.

        Args:
            error: The exception to raise or log.
            guardrail_name: Name of the guardrail.
            check_type: Hook method that detected the violation.
            additional_info: Optional context passed to the on_fail callback.
            input_data: The data that triggered the violation.
        """
        if self.on_fail is not None:
            context: Dict[str, Any] = {
                "guardrail_name": guardrail_name,
                "check_type": check_type,
            }
            if additional_info:
                context["additional_info"] = additional_info
            try:
                self.on_fail(error, input_data, context)
            except Exception as callback_error:
                log_warning(f"on_fail callback raised an exception: {callback_error}")

        if self.dry_run:
            log_warning(f"{guardrail_name}.{check_type} would block: {error}")
        else:
            raise error

    # ----- Pre-hook methods -----

    def pre_check(self, run_input: Union[RunInput, TeamRunInput]) -> None:
        """Check input before the model is called."""
        pass

    async def async_pre_check(self, run_input: Union[RunInput, TeamRunInput]) -> None:
        """Async check input before the model is called."""
        pass

    # ----- Model-hook methods -----

    def model_check(self, run_messages: RunMessages, **kwargs: Any) -> None:
        """Check messages before each model invocation."""
        pass

    async def async_model_check(self, run_messages: RunMessages, **kwargs: Any) -> None:
        """Async check messages before each model invocation."""
        pass

    # ----- Post-hook methods -----

    def post_check(self, run_output: Union[RunOutput, TeamRunOutput]) -> None:
        """Check output after the model responds."""
        pass

    async def async_post_check(self, run_output: Union[RunOutput, TeamRunOutput]) -> None:
        """Async check output after the model responds."""
        pass

    # ----- Deprecated methods -----

    def check(self, run_input: Union[RunInput, TeamRunInput]) -> None:
        """Deprecated. Use pre_check() instead."""
        import warnings

        warnings.warn(
            "check() is deprecated and will be removed in a future version. Use pre_check() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.pre_check(run_input)

    async def async_check(self, run_input: Union[RunInput, TeamRunInput]) -> None:
        """Deprecated. Use async_pre_check() instead."""
        import warnings

        warnings.warn(
            "async_check() is deprecated and will be removed in a future version. Use async_pre_check() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return await self.async_pre_check(run_input)
