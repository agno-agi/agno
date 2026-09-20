import json
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from agno.models.typesafe._client import DecisionResult, JevClient
from agno.models.typesafe._schemas import compile_decisions, json_schema, json_state
from agno.tools import Toolkit


class JevTools(Toolkit):
    """Let a generative model consult Jev for typed decisions.

    Fixed questions are the default. Dynamic question construction must be
    explicitly enabled; it never exposes model or connection configuration.
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
        **kwargs: Any,
    ):
        self.schema = (
            compile_decisions(questions, output_schema) if questions is not None or output_schema is not None else None
        )
        if self.schema is None and not allow_dynamic_questions:
            raise ValueError("JevTools needs fixed questions/output_schema or allow_dynamic_questions=True")
        self.input_schema = input_schema
        self.allow_dynamic_questions = allow_dynamic_questions
        self.sdk = JevClient(model, api_key, base_url, timeout, client, async_client)
        tools: List[Callable[..., Any]] = [self.evaluate] if self.schema is not None else []
        async_tools: List[Tuple[Callable[..., Any], str]] = (
            [(self.aevaluate, "evaluate")] if self.schema is not None else []
        )
        if allow_dynamic_questions:
            tools.append(self.evaluate_questions)
            async_tools.append((self.aevaluate_questions, "evaluate_questions"))
        super().__init__(name="jev_tools", tools=tools, async_tools=async_tools, **kwargs)
        state_schema = (
            json_schema(input_schema)
            if input_schema is not None
            else {"anyOf": [{"type": "string"}, {"type": "object"}, {"type": "array"}]}
        )
        for collection in (self.functions, self.async_functions):
            for name, function in collection.items():
                properties = {"state": state_schema}
                if name == "evaluate_questions":
                    properties["questions"] = {
                        "type": "object",
                        "description": "Question ID to question. Each question needs type (noul, choice, score), instructions, and criteria (choice: label to description; score: 2-10 ordered descriptions). IDs are not visible to Jev. Questions are independent.",
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
        if self.schema is None:
            raise ValueError("No fixed questions configured")
        return self._serialize(self.sdk.evaluate(self._state(state), self.schema))

    async def aevaluate(self, state: Any) -> str:
        """Asynchronously evaluate developer-defined questions."""
        if self.schema is None:
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
