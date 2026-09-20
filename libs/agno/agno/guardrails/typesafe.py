import json
from copy import copy
from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel

from agno.exceptions import CheckTrigger, InputCheckError, OutputCheckError
from agno.guardrails.base import BaseGuardrail
from agno.run.agent import RunInput, RunOutput
from agno.run.team import TeamRunInput, TeamRunOutput
from agno.utils.log import log_debug, log_warning
from agno.utils.typesafe import GUARDRAIL_PRESETS, answers_to_dict, noul_question

DEFAULT_CHECKS = ["prompt_injection", "harmful_request"]


@dataclass
class _Check:
    id: str
    input_question: Dict[str, Any]
    output_question: Dict[str, Any]
    threshold: float
    input_trigger: CheckTrigger
    output_trigger: CheckTrigger


def _trigger(value: Union[CheckTrigger, str]) -> CheckTrigger:
    if isinstance(value, CheckTrigger):
        return value
    try:
        return CheckTrigger[value.upper()]
    except KeyError:
        return CheckTrigger(value)


class JevGuardrail(BaseGuardrail):
    """Guardrail that screens run input or output with Jev, TypeSafe's System One model.

    Each check is a yes/no question. Jev returns the probability that the answer is yes, and
    the run is blocked when a probability reaches the check's threshold. Every check goes out
    in one request, so adding checks does not add round trips.

    Use it in `pre_hooks` to screen what the user sent, in `post_hooks` to screen the reply, or both.
    Screening a streamed reply happens after its tokens were sent; it stops the run, not the text.

    Args:
        checks (List[str]): Built-in checks to run. Options are: "prompt_injection", "harmful_request",
            "self_harm", "medical_advice", "pii", "toxicity". Defaults to "prompt_injection" and
            "harmful_request" when no checks and no questions are given.
        questions (Dict[str, Union[str, Dict]]): Your own checks, keyed by an id of your choice. A value is the
            yes/no question, where yes means block - or a dict with "instructions", and optionally
            "criteria" ({"true": ..., "false": ...}), "threshold" and "check_trigger".
            Write each question literally and about one thing; Jev answers the words on the page.
        threshold (float): Block when a probability reaches this. Defaults to 0.7.
        fail_closed (bool): Block the run when Jev cannot be reached. By default the failure is logged
            and the run continues.
        id (str): The Jev model to use. Defaults to "jev-latest".
        api_key (str): The API key to use. Defaults to the TYPESAFE_API_KEY environment variable.
        base_url (str): Override the TypeSafe API root.
        timeout (float): Seconds to wait for Jev before the check counts as failed.
    """

    def __init__(
        self,
        checks: Optional[List[str]] = None,
        questions: Optional[Dict[str, Union[str, Dict[str, Any]]]] = None,
        threshold: float = 0.7,
        fail_closed: bool = False,
        id: str = "jev-latest",
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
    ):
        self.id = id
        self.api_key = api_key or getenv("TYPESAFE_API_KEY")
        self.base_url = base_url
        self.timeout = timeout
        self.threshold = threshold
        self.fail_closed = fail_closed
        self.client: Any = None
        self.async_client: Any = None

        if checks is None and not questions:
            checks = DEFAULT_CHECKS
        self.checks: List[_Check] = []
        for name in checks or []:
            preset = GUARDRAIL_PRESETS.get(name)
            if preset is None:
                raise ValueError(f"Unknown check '{name}'. Options are: {', '.join(sorted(GUARDRAIL_PRESETS))}")
            self.checks.append(
                _Check(
                    id=name,
                    input_question=preset["input"],
                    output_question=preset["output"],
                    threshold=threshold,
                    input_trigger=CheckTrigger[preset["trigger"]],
                    output_trigger=CheckTrigger.OUTPUT_NOT_ALLOWED,
                )
            )
        for check_id, spec in (questions or {}).items():
            self.checks.append(self._custom_check(check_id, spec))

    def _custom_check(self, check_id: str, spec: Union[str, Dict[str, Any]]) -> _Check:
        if any(existing.id == check_id for existing in self.checks):
            raise ValueError(f"Check id '{check_id}' is used twice.")
        if isinstance(spec, str):
            spec = {"instructions": spec}
        if spec.get("type", "noul") != "noul":
            raise ValueError(
                f"Check '{check_id}' must be a noul (yes/no) question; a guardrail blocks on a probability."
            )
        if not spec.get("instructions"):
            raise ValueError(f"Check '{check_id}' needs `instructions`: the yes/no question to ask.")
        question = noul_question(spec["instructions"], spec.get("criteria"))
        trigger = spec.get("check_trigger")
        return _Check(
            id=check_id,
            input_question=question,
            output_question=question,
            threshold=float(spec.get("threshold", self.threshold)),
            input_trigger=_trigger(trigger) if trigger is not None else CheckTrigger.INPUT_NOT_ALLOWED,
            output_trigger=_trigger(trigger) if trigger is not None else CheckTrigger.OUTPUT_NOT_ALLOWED,
        )

    def __deepcopy__(self, memo: Dict[int, Any]) -> "JevGuardrail":
        # Clients hold open connections; a copy builds its own on first use
        copied = copy(self)
        copied.client = None
        copied.async_client = None
        return copied

    def _client_params(self) -> Dict[str, Any]:
        params: Dict[str, Any] = {"api_key": self.api_key, "model": self.id}
        if self.base_url is not None:
            params["base_url"] = self.base_url
        if self.timeout is not None:
            params["timeout"] = self.timeout
        return params

    def _content(
        self,
        run_input: Optional[Union[RunInput, TeamRunInput]],
        run_output: Optional[Union[RunOutput, TeamRunOutput]],
    ) -> str:
        if run_input is not None:
            return run_input.input_content_string()
        content = getattr(run_output, "content", None)
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        if isinstance(content, BaseModel):
            return content.model_dump_json(exclude_none=True)
        return json.dumps(content, default=str)

    def _questions(self, on_output: bool) -> Dict[str, Dict[str, Any]]:
        return {c.id: (c.output_question if on_output else c.input_question) for c in self.checks}

    def _evaluate(self, response: Any, on_output: bool) -> None:
        answers = answers_to_dict(getattr(response, "answers", None))
        probabilities = {check_id: answer.get("noul") for check_id, answer in answers.items()}
        failed = [c for c in self.checks if (probabilities.get(c.id) or 0.0) >= c.threshold]
        log_debug(f"Jev guardrail probabilities: {probabilities}")
        if not failed:
            return

        side = "output" if on_output else "input"
        details = ", ".join(f"{c.id} ({probabilities[c.id]:.2f})" for c in failed)
        additional_data = {
            "failed": [c.id for c in failed],
            "probabilities": probabilities,
            "thresholds": {c.id: c.threshold for c in self.checks},
            "model": getattr(response, "model", None),
            "request_id": getattr(response, "request_id", None),
        }
        message = f"Jev guardrail blocked the {side}: {details}"
        if on_output:
            raise OutputCheckError(message, check_trigger=failed[0].output_trigger, additional_data=additional_data)
        raise InputCheckError(message, check_trigger=failed[0].input_trigger, additional_data=additional_data)

    def _unavailable(self, error: Exception, on_output: bool) -> None:
        """Jev could not be asked. Any exception other than a check error is dropped by the hook runner,
        so failing closed has to be raised as a check error."""
        if not self.fail_closed:
            log_warning(f"Jev guardrail could not be evaluated, continuing the run: {error}")
            return
        message = f"Jev guardrail could not be evaluated: {error}"
        additional_data = {"error": str(error)}
        if on_output:
            raise OutputCheckError(
                message, check_trigger=CheckTrigger.OUTPUT_NOT_ALLOWED, additional_data=additional_data
            )
        raise InputCheckError(message, check_trigger=CheckTrigger.INPUT_NOT_ALLOWED, additional_data=additional_data)

    def check(
        self,
        run_input: Optional[Union[RunInput, TeamRunInput]] = None,
        run_output: Optional[Union[RunOutput, TeamRunOutput]] = None,
    ) -> None:
        """Screen the run input (as a pre-hook) or the run output (as a post-hook)."""
        on_output = run_input is None
        content = self._content(run_input, run_output)
        if not content or not self.checks:
            return

        try:
            if self.client is None:
                try:
                    from typesafe_sdk import TypeSafeClient
                except ImportError:
                    raise ImportError(
                        "`typesafe-sdk` not installed. Please install using `pip install typesafe-sdk` "
                        "(requires Python >= 3.10)"
                    )
                self.client = TypeSafeClient(**self._client_params())
            state = {"response": content} if on_output else {"message": content}
            response = self.client.system_one(state, self._questions(on_output))
        except Exception as e:
            self._unavailable(e, on_output)
            return
        self._evaluate(response, on_output)

    async def async_check(
        self,
        run_input: Optional[Union[RunInput, TeamRunInput]] = None,
        run_output: Optional[Union[RunOutput, TeamRunOutput]] = None,
    ) -> None:
        """Screen the run input (as a pre-hook) or the run output (as a post-hook)."""
        on_output = run_input is None
        content = self._content(run_input, run_output)
        if not content or not self.checks:
            return

        try:
            if self.async_client is None:
                try:
                    from typesafe_sdk import AsyncTypeSafeClient
                except ImportError:
                    raise ImportError(
                        "`typesafe-sdk` not installed. Please install using `pip install typesafe-sdk` "
                        "(requires Python >= 3.10)"
                    )
                self.async_client = AsyncTypeSafeClient(**self._client_params())
            state = {"response": content} if on_output else {"message": content}
            response = await self.async_client.system_one(state, self._questions(on_output))
        except Exception as e:
            self._unavailable(e, on_output)
            return
        self._evaluate(response, on_output)
