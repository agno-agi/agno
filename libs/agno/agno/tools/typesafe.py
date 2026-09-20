import json
from os import getenv
from typing import Any, Dict, List, Literal, Optional, Type

from pydantic import BaseModel, Field

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error
from agno.utils.typesafe import (
    SchemaPlan,
    answers_to_dict,
    answers_to_values,
    choice_question,
    noul_question,
    schema_to_questions,
    score_question,
)

JEV_INSTRUCTIONS = """\
Jev is a fast decision model. It does not write text: it reads a `state` and answers typed questions about it
with calibrated probabilities. Use it for judgments you would otherwise guess at - classifying, checking a
claim against evidence, rating, ranking candidates, or turning free text into numbers you can compare.

Writing questions for Jev:
- One snap judgment per question. Split a broad question into several narrow ones and combine the answers yourself.
- Jev reads literally. State the exact condition; do not rely on implied meaning or on the question id.
- noul: a yes/no question. The answer is the probability of yes. Leave `options` empty.
- choice: pick one of `options`. Add an option such as "none of these" when nothing may fit.
- score: rate along `options`, which are 2 to 10 level descriptions ordered from lowest to highest.
- Put every question about the same state in ONE call. Questions run in parallel and cannot see each other's answers.
- Keep the state to what the questions need. Put several parts in a JSON object with named fields, and point a
  question at a part with a backticked path such as `ticket.message`.
- Do counting, arithmetic and date comparison yourself. Jev is unreliable at them.
- A noul near 0.5, or a low `confidence`, means Jev is unsure. Treat it as unsure, not as a weak yes.\
"""


class JevQuestion(BaseModel):
    """One typed question for Jev."""

    id: str = Field(description="A short id for this question. The answer comes back under it.")
    type: Literal["noul", "choice", "score"] = Field(
        description="noul = yes/no probability, choice = pick one option, score = rate along ordered levels."
    )
    instructions: str = Field(description="The question itself, written out in full and literally.")
    options: List[str] = Field(
        description="choice: the options to pick from. score: 2 to 10 level descriptions, lowest first. noul: empty."
    )


class JevTools(Toolkit):
    """Tools that let an agent ask Jev, TypeSafe's System One model, for typed judgments."""

    def __init__(
        self,
        output_schema: Optional[Type[BaseModel]] = None,
        questions: Optional[Dict[str, Any]] = None,
        api_key: Optional[str] = None,
        model: str = "jev-latest",
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
        threshold: float = 0.5,
        enable_evaluate: bool = True,
        enable_ask_jev: bool = True,
        all: bool = False,
        **kwargs,
    ):
        """Initialize the Jev toolkit.

        Args:
            output_schema: Fixed questions for the `evaluate` tool, as a pydantic model: bool, Literal, Enum,
                IntEnum and List[Literal] fields, each asked using the field description.
            questions: Fixed questions for the `evaluate` tool, as raw System One question dicts keyed by id.
                Use this or `output_schema`, not both.
            api_key: TypeSafe API key. Uses ``TYPESAFE_API_KEY`` when omitted.
            model: The Jev model to use.
            base_url: Override the TypeSafe API root.
            timeout: Per-request timeout in seconds.
            threshold: A yes/no probability at or above this counts as yes when filling `output_schema`.
            enable_evaluate: Register `evaluate`, which answers the fixed questions about a state the agent
                supplies. Only registered when `output_schema` or `questions` is given.
            enable_ask_jev: Register `ask_jev`, where the agent writes the questions itself.
            all: Register all tools regardless of individual flags.
        """
        if output_schema is not None and questions is not None:
            raise ValueError("Give JevTools an output_schema or questions, not both.")

        self.api_key = api_key or getenv("TYPESAFE_API_KEY")
        self.model = model
        self.base_url = base_url
        self.request_timeout = timeout
        self.client: Any = None
        self.async_client: Any = None
        self.schema_plan: Optional[SchemaPlan] = (
            schema_to_questions(output_schema, threshold) if output_schema is not None else None
        )
        self.fixed_questions: Optional[Dict[str, Any]] = (
            self.schema_plan.questions if self.schema_plan is not None else questions
        )

        if not self.api_key:
            log_error("TYPESAFE_API_KEY not set. Please set the TYPESAFE_API_KEY environment variable.")

        tools: List[Any] = []
        async_tools: List[tuple] = []
        if (all or enable_evaluate) and self.fixed_questions:
            tools.append(self.evaluate)
            async_tools.append((self.aevaluate, "evaluate"))
        if all or enable_ask_jev:
            tools.append(self.ask_jev)
            async_tools.append((self.aask_jev, "ask_jev"))

        name = kwargs.pop("name", "jev_tools")
        instructions = kwargs.pop("instructions", JEV_INSTRUCTIONS)
        add_instructions = kwargs.pop("add_instructions", True)
        super().__init__(
            name=name,
            tools=tools,
            async_tools=async_tools,
            instructions=instructions,
            add_instructions=add_instructions,
            **kwargs,
        )

    def _client_params(self) -> Dict[str, Any]:
        if not self.api_key:
            raise ValueError("TypeSafe API key is required. Set TYPESAFE_API_KEY or pass api_key.")
        params: Dict[str, Any] = {"api_key": self.api_key, "model": self.model}
        if self.base_url is not None:
            params["base_url"] = self.base_url
        if self.request_timeout is not None:
            params["timeout"] = self.request_timeout
        return params

    def _get_client(self) -> Any:
        if self.client is None:
            try:
                from typesafe_sdk import TypeSafeClient
            except ImportError:
                raise ImportError(
                    "`typesafe-sdk` not installed. Please install using `pip install typesafe-sdk` "
                    "(requires Python >= 3.10)"
                )
            self.client = TypeSafeClient(**self._client_params())
        return self.client

    def _get_async_client(self) -> Any:
        if self.async_client is None:
            try:
                from typesafe_sdk import AsyncTypeSafeClient
            except ImportError:
                raise ImportError(
                    "`typesafe-sdk` not installed. Please install using `pip install typesafe-sdk` "
                    "(requires Python >= 3.10)"
                )
            self.async_client = AsyncTypeSafeClient(**self._client_params())
        return self.async_client

    @staticmethod
    def _state(state: str) -> Any:
        """A state written as a JSON object or array is sent structured, so questions can point at its parts."""
        text = state.strip()
        if text[:1] in ("{", "["):
            try:
                return json.loads(text)
            except ValueError:
                pass
        return state

    @staticmethod
    def _build_questions(questions: List[JevQuestion]) -> Dict[str, Dict[str, Any]]:
        built: Dict[str, Dict[str, Any]] = {}
        for question in questions:
            if question.id in built:
                raise ValueError(f"Question id '{question.id}' is used twice.")
            if question.type == "noul":
                built[question.id] = noul_question(question.instructions)
            elif question.type == "choice":
                built[question.id] = choice_question(
                    question.instructions, {option: None for option in question.options}
                )
            else:
                built[question.id] = score_question(question.instructions, question.options)
        if not built:
            raise ValueError("Give Jev at least one question.")
        return built

    def _evaluate_result(self, response: Any) -> str:
        answers = answers_to_dict(getattr(response, "answers", None))
        result: Dict[str, Any] = {"answers": answers}
        if self.schema_plan is not None:
            values = self.schema_plan.model.model_validate(answers_to_values(answers, self.schema_plan))
            result = {"values": values.model_dump(mode="json"), "answers": answers}
        return json.dumps(result)

    def evaluate(self, state: str) -> str:
        """Judge a piece of content with Jev, using the questions this tool was set up with.

        Args:
            state: The content to judge: plain text, or a JSON object with named parts.

        Returns:
            JSON with Jev's answers, including a probability or confidence for each.
        """
        try:
            log_debug(f"Asking Jev {len(self.fixed_questions or {})} fixed question(s)")
            response = self._get_client().system_one(self._state(state), self.fixed_questions)
            return self._evaluate_result(response)
        except Exception as e:
            log_error(f"Jev evaluate failed: {e}")
            return json.dumps({"error": str(e)})

    async def aevaluate(self, state: str) -> str:
        """Judge a piece of content with Jev, using the questions this tool was set up with.

        Args:
            state: The content to judge: plain text, or a JSON object with named parts.

        Returns:
            JSON with Jev's answers, including a probability or confidence for each.
        """
        try:
            log_debug(f"Asking Jev {len(self.fixed_questions or {})} fixed question(s)")
            response = await self._get_async_client().system_one(self._state(state), self.fixed_questions)
            return self._evaluate_result(response)
        except Exception as e:
            log_error(f"Jev evaluate failed: {e}")
            return json.dumps({"error": str(e)})

    def ask_jev(self, state: str, questions: List[JevQuestion]) -> str:
        """Ask Jev typed questions about a piece of content. Send every question about the same state in one call.

        Args:
            state: The content to judge: plain text, or a JSON object with named parts.
            questions: The questions to ask about the state.

        Returns:
            JSON with one answer per question id: `noul` is the probability of yes; `choice` and `score`
            come with `probabilities` and a `confidence`.
        """
        try:
            built = self._build_questions(questions)
            log_debug(f"Asking Jev {len(built)} question(s)")
            response = self._get_client().system_one(self._state(state), built)
            return json.dumps({"answers": answers_to_dict(getattr(response, "answers", None))})
        except Exception as e:
            log_error(f"Jev ask_jev failed: {e}")
            return json.dumps({"error": str(e)})

    async def aask_jev(self, state: str, questions: List[JevQuestion]) -> str:
        """Ask Jev typed questions about a piece of content. Send every question about the same state in one call.

        Args:
            state: The content to judge: plain text, or a JSON object with named parts.
            questions: The questions to ask about the state.

        Returns:
            JSON with one answer per question id: `noul` is the probability of yes; `choice` and `score`
            come with `probabilities` and a `confidence`.
        """
        try:
            built = self._build_questions(questions)
            log_debug(f"Asking Jev {len(built)} question(s)")
            response = await self._get_async_client().system_one(self._state(state), built)
            return json.dumps({"answers": answers_to_dict(getattr(response, "answers", None))})
        except Exception as e:
            log_error(f"Jev ask_jev failed: {e}")
            return json.dumps({"error": str(e)})
