import json
from typing import Any, Callable, Dict, List, Literal, Mapping, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from agno.models.typesafe._client import DecisionResult, JevClient
from agno.models.typesafe._schemas import compile_decisions, json_schema, json_state
from agno.tools import Toolkit


JEV_INSTRUCTIONS = """Jev judges supplied text or JSON; it does not generate prose.
Use evaluate for developer-defined questions, or ask_jev to define questions when available.
With ask_jev, put related material in named JSON fields and refer to those fields explicitly.
Write narrow, literal instructions: Jev cannot see question IDs. Each question is independent;
batch questions about the same state, but never refer to another question's answer.
For noul questions, use options=[]; the answer is a probability from 0 to 1, not a boolean.
For choice questions, list distinct labels (include a none/other label when appropriate).
For score questions, supply 2-10 ordered descriptions; the answer is a fractional position
starting at zero. Keep the same questions and rubrics when comparing different texts.
Use code for counting, arithmetic and date calculations. Treat uncertain judgments as uncertain.
"""


class JevQuestion(BaseModel):
    """An LLM-authored question; Agno translates options into the SDK's criteria."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str = Field(min_length=1, description="Unique answer ID. This ID is not visible to Jev.")
    type: Literal["noul", "choice", "score"]
    instructions: str = Field(min_length=1, description="The complete, literal question to ask about state.")
    options: List[str] = Field(
        description="noul: []; choice: 1-255 distinct labels; score: 2-10 descriptions in ascending order."
    )


class JevTools(Toolkit):
    """Let a generative model consult Jev for typed decisions.

    With no schema, expose ask_jev so the LLM can author questions. A fixed schema
    exposes evaluate; add enable_ask_jev=True to offer both operations.
    """

    def __init__(
        self,
        questions: Optional[Mapping[str, Any]] = None,
        output_schema: Any = None,
        input_schema: Any = None,
        allow_dynamic_questions: bool = False,
        model: str = "jev-latest",
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
        client: Any = None,
        async_client: Any = None,
        enable_evaluate: bool = True,
        enable_ask_jev: Optional[bool] = None,
        **kwargs: Any,
    ):
        self.schema = (
            compile_decisions(questions, output_schema) if questions is not None or output_schema is not None else None
        )
        self.enable_evaluate = enable_evaluate
        self.enable_ask_jev = (
            self.schema is None and not allow_dynamic_questions if enable_ask_jev is None else enable_ask_jev
        )
        self.input_schema = input_schema
        self.allow_dynamic_questions = allow_dynamic_questions
        self.sdk = JevClient(model, api_key, base_url, timeout, client, async_client)
        fixed = self.schema is not None and enable_evaluate
        tools: List[Callable[..., Any]] = [self.evaluate] if fixed else []
        async_tools: List[Tuple[Callable[..., Any], str]] = [(self.aevaluate, "evaluate")] if fixed else []
        if self.enable_ask_jev:
            tools.append(self.ask_jev)
            async_tools.append((self.aask_jev, "ask_jev"))
        if allow_dynamic_questions:
            tools.append(self.evaluate_questions)
            async_tools.append((self.aevaluate_questions, "evaluate_questions"))
        if not tools:
            raise ValueError("Enable ask_jev, dynamic questions, or evaluate with a fixed schema")
        kwargs.setdefault("name", "jev_tools")
        kwargs.setdefault("instructions", JEV_INSTRUCTIONS)
        kwargs.setdefault("add_instructions", True)
        super().__init__(tools=tools, async_tools=async_tools, **kwargs)
        state_schema = (
            json_schema(input_schema)
            if input_schema is not None
            else {"anyOf": [{"type": "string"}, {"type": "object"}, {"type": "array"}]}
        )
        for collection in (self.functions, self.async_functions):
            for name, function in collection.items():
                if name == "ask_jev":
                    questions_schema = TypeAdapter(List[JevQuestion]).json_schema()
                    function.parameters = {
                        "type": "object",
                        "properties": {
                            "state": {
                                "type": "string",
                                "description": "Text or a JSON-encoded object/array. Decoded JSON is passed directly as state.",
                            },
                            "questions": {"type": "array", "items": questions_schema["items"], "minItems": 1},
                        },
                        "required": ["state", "questions"],
                        "additionalProperties": False,
                        "$defs": questions_schema["$defs"],
                    }
                    function.description = "Ask Jev independent typed questions about text or JSON. Returns values and raw answer probabilities."
                    function.skip_entrypoint_processing = True
                    continue
                properties = {"state": state_schema}
                if name == "evaluate_questions":
                    properties["questions"] = {
                        "type": "object",
                        "description": 'Question ID to question. Each needs type and instructions. criteria: noul omit or {"true": "yes description", "false": "no description"} (never yes/no keys); choice: label to description; score: 2-10 ordered descriptions. IDs are invisible. Questions are independent. Prefer ask_jev when available.',
                    }
                function.parameters = {"type": "object", "properties": properties, "required": list(properties)}
                # Input schemas may contain local definitions; hoist them for valid references.
                if "$defs" in state_schema:
                    function.parameters["$defs"] = state_schema["$defs"]
                function.description = "Evaluate the supplied state with Jev's typed decisions. Returns values and raw answer probabilities."
                function.skip_entrypoint_processing = True

    @staticmethod
    def _serialize(result: DecisionResult) -> str:
        return json.dumps({"values": result.values, "typesafe": result.metadata}, ensure_ascii=False)

    def _state(self, state: Any) -> Dict[str, Any]:
        return {"input": json_state(state, self.input_schema)}

    def evaluate(self, state: Any) -> str:
        """Evaluate developer-defined questions against state.input."""
        if self.schema is None or not self.enable_evaluate:
            raise ValueError("No fixed questions configured")
        return self._serialize(self.sdk.evaluate(self._state(state), self.schema))

    async def aevaluate(self, state: Any) -> str:
        """Asynchronously evaluate developer-defined questions."""
        if self.schema is None or not self.enable_evaluate:
            raise ValueError("No fixed questions configured")
        return self._serialize(await self.sdk.aevaluate(self._state(state), self.schema))

    def evaluate_questions(self, state: Any, questions: Dict[str, Any]) -> str:
        """Evaluate caller-defined independent questions; explicitly opt in first."""
        if not self.allow_dynamic_questions:
            raise ValueError("Dynamic Jev questions are disabled")
        schema = compile_decisions(questions)
        return self._serialize(self.sdk.evaluate(self._state(state), schema))

    async def aevaluate_questions(self, state: Any, questions: Dict[str, Any]) -> str:
        """Asynchronously evaluate caller-defined questions."""
        if not self.allow_dynamic_questions:
            raise ValueError("Dynamic Jev questions are disabled")
        schema = compile_decisions(questions)
        return self._serialize(await self.sdk.aevaluate(self._state(state), schema))

    def _ask_state(self, state: str) -> Any:
        try:
            parsed = json.loads(state)
        except (ValueError, TypeError):
            parsed = state
        return json_state(parsed if isinstance(parsed, (dict, list)) else state, self.input_schema)

    @staticmethod
    def _ask_schema(questions: List[JevQuestion]) -> Any:
        questions = TypeAdapter(List[JevQuestion]).validate_python(questions)
        compiled: Dict[str, Any] = {}
        for question in questions:
            if question.id in compiled:
                raise ValueError(f"Duplicate question ID: {question.id!r}")
            options = question.options
            if any(not option.strip() for option in options) or len(set(options)) != len(options):
                raise ValueError("Question options must be nonempty and distinct")
            spec: Dict[str, Any] = {"type": question.type, "instructions": question.instructions}
            if question.type == "noul":
                if options:
                    raise ValueError("Noul questions need options=[]")
            else:
                spec["criteria"] = {option: None for option in options} if question.type == "choice" else options
            compiled[question.id] = spec
        return compile_decisions(compiled)

    def ask_jev(self, state: str, questions: List[JevQuestion]) -> str:
        """Ask independent questions about text or a JSON-encoded state object/array."""
        if not self.enable_ask_jev:
            raise ValueError("ask_jev is disabled")
        schema = self._ask_schema(questions)
        return self._serialize(self.sdk.evaluate(self._ask_state(state), schema))

    async def aask_jev(self, state: str, questions: List[JevQuestion]) -> str:
        """Asynchronously ask independent questions about supplied text or JSON."""
        if not self.enable_ask_jev:
            raise ValueError("ask_jev is disabled")
        schema = self._ask_schema(questions)
        return self._serialize(await self.sdk.aevaluate(self._ask_state(state), schema))
