"""Compile finite decisions without asking Jev to generate JSON or free text."""

import json
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Tuple, Type

from pydantic import BaseModel

try:
    from typesafe_sdk import Choice, Noul, Score
except ImportError as exc:
    raise ImportError(
        "Jev requires Python 3.10+ and typesafe-sdk>=0.7.0. Install with `pip install 'agno[typesafe]'`."
    ) from exc


def question_dict(question: Any) -> Dict[str, Any]:
    if isinstance(question, (Choice, Noul, Score)):
        return question.model_dump(mode="json", exclude_none=True)
    if isinstance(question, Mapping):
        return dict(question)
    raise ValueError("Expected an SDK Choice, Noul, Score, or its JSON representation")


def questions_dict(questions: Mapping[str, Any]) -> Dict[str, Any]:
    if not questions:
        raise ValueError("Jev needs at least one question")
    return {key: question_dict(question) for key, question in questions.items()}


def validate_questions(questions: Mapping[str, Any]) -> Dict[str, Any]:
    result = {}
    for key, data in questions_dict(questions).items():
        if not isinstance(key, str) or not key:
            raise ValueError("Question IDs must be nonempty strings")
        if not data.get("instructions"):
            raise ValueError(f"Question {key!r} needs instructions; question IDs are not visible to Jev")
        kind = data.get("type")
        classes: Dict[str, Type[BaseModel]] = {"noul": Noul, "choice": Choice, "score": Score}
        cls = classes.get(kind)
        if cls is None:
            raise ValueError(f"Unsupported Jev question type: {kind!r}")
        if kind == "choice" and not 1 <= len(data.get("criteria", {})) <= 255:
            raise ValueError("Choice needs between 1 and 255 options")
        if kind == "score" and not 2 <= len(data.get("criteria", [])) <= 10:
            raise ValueError("Score needs between 2 and 10 ordered criteria")
        result[key] = cls.model_validate(data)
    return result


@dataclass(frozen=True)
class JevField:
    """Attach a question to Annotated[float/str/bool, JevField(...)].

    Noul yields a probability unless a boolean field supplies an explicit threshold.
    Score yields a fractional position in its ordered criteria, starting at zero.
    """

    question: Any
    threshold: Optional[float] = None

    def __get_pydantic_json_schema__(self, core_schema: Any, handler: Any) -> Dict[str, Any]:
        schema = dict(handler(core_schema))
        schema["x-jev"] = {"question": question_dict(self.question)}
        if self.threshold is not None:
            schema["x-jev"]["threshold"] = self.threshold
        return schema


def json_schema(schema: Any) -> Dict[str, Any]:
    if isinstance(schema, type) and issubclass(schema, BaseModel):
        return schema.model_json_schema()
    if isinstance(schema, dict):
        if schema.get("type") == "json_schema":
            return schema["json_schema"]["schema"]
        return schema
    raise ValueError("Expected a Pydantic model class or JSON schema")


def resolve_ref(node: Dict[str, Any], root: Dict[str, Any], seen: Tuple[str, ...] = ()) -> Dict[str, Any]:
    if "$ref" not in node:
        return node
    ref = node["$ref"]
    if ref in seen or not ref.startswith("#/$defs/"):
        raise ValueError("Jev does not support recursive or external schema references")
    target = root.get("$defs", {}).get(ref[len("#/$defs/") :])
    if target is None:
        raise ValueError(f"Unresolved schema reference: {ref}")
    return {**resolve_ref(target, root, (*seen, ref)), **{k: v for k, v in node.items() if k != "$ref"}}


@dataclass
class DecisionSchema:
    questions: Dict[str, Any]
    # Question ID -> (JSON output path, optional boolean threshold)
    fields: Dict[str, Tuple[Tuple[str, ...], Optional[float]]]
    output_schema: Any = None
    validator: Any = None

    def values(self, answers: Mapping[str, Any]) -> Dict[str, Any]:
        if set(answers) != set(self.questions):
            raise ValueError("Jev returned missing or unexpected answers")
        result: Dict[str, Any] = {}
        for key, question in self.questions.items():
            answer = answers[key]
            kind = question.type
            if answer.type != kind:
                raise ValueError(f"Jev returned the wrong answer type for {key!r}")
            value = getattr(answer, kind)
            if kind == "choice" and value not in question.criteria:
                raise ValueError(f"Jev returned an unknown choice for {key!r}")
            if kind == "score" and not 0 <= value <= len(question.criteria) - 1:
                raise ValueError(f"Jev returned an out-of-range score for {key!r}")
            path, threshold = self.fields[key]
            if threshold is not None:
                value = value >= threshold
            cursor = result
            for part in path[:-1]:
                cursor = cursor.setdefault(part, {})
            cursor[path[-1]] = value
        if isinstance(self.output_schema, type) and issubclass(self.output_schema, BaseModel):
            # Validate custom validators and constraints without changing JSON aliases.
            self.output_schema.model_validate(result)
        if self.validator is not None:
            self.validator.validate(result)
        return result


def compile_decisions(questions: Optional[Mapping[str, Any]] = None, output_schema: Any = None) -> DecisionSchema:
    if questions is not None:
        if output_schema is not None:
            raise ValueError("Choose questions or an annotated output_schema, not both")
        validated = validate_questions(questions)
        return DecisionSchema(validated, {key: ((key,), None) for key in validated})
    if output_schema is None:
        raise ValueError("Jev cannot generate free text. Supply questions or an output_schema annotated with JevField.")
    root = deepcopy(json_schema(output_schema))
    validator = None
    if isinstance(output_schema, dict):
        try:
            from jsonschema import Draft202012Validator
        except ImportError as exc:
            raise ImportError(
                "Serialized Jev output schemas require jsonschema. Install `pip install 'agno[typesafe]'`."
            ) from exc
        Draft202012Validator.check_schema(root)
        validator = Draft202012Validator(root)
    compiled: Dict[str, Any] = {}
    fields = {}

    def visit(node: Dict[str, Any], path: Tuple[str, ...], refs: Tuple[str, ...]) -> None:
        ref = node.get("$ref")
        if ref and ref in refs:
            raise ValueError("Jev does not support recursive schemas")
        node = resolve_ref(node, root)
        refs = (*refs, ref) if ref else refs
        annotation = node.get("x-jev")
        if annotation is None and node.get("type") == "object":
            properties = node.get("properties", {})
            if not properties or node.get("additionalProperties") not in (None, False):
                raise ValueError("Jev output objects need fixed, nonempty properties")
            for name, child in properties.items():
                visit(child, (*path, name), refs)
            return
        if not path or annotation is None:
            raise ValueError(f"Output field {'.'.join(path)!r} needs JevField metadata")
        data = dict(annotation["question"])
        threshold = annotation.get("threshold")
        kind, field_type = data.get("type"), node.get("type")
        if kind == "choice":
            if field_type != "string" or threshold is not None:
                raise ValueError("Choice output fields must be strings, string Literals, or string Enums")
            permitted = node.get("enum", [node["const"]] if "const" in node else None)
            if permitted is not None and set(permitted) != set(data.get("criteria", {})):
                raise ValueError("Choice criteria must match the field's allowed values")
        elif kind == "noul" and field_type == "boolean":
            if threshold is None or not 0 <= threshold <= 1:
                raise ValueError("Boolean Noul fields require an explicit threshold between 0 and 1")
        elif kind not in ("noul", "score") or field_type != "number" or threshold is not None:
            raise ValueError("Noul and Score need float fields; only boolean Noul supports a threshold")
        data["instructions"] = {"field": ".".join(path), "instructions": data.get("instructions")}
        key = f"q{len(compiled)}"
        compiled[key] = data
        fields[key] = (path, threshold)

    visit(root, (), ())
    return DecisionSchema(validate_questions(compiled), fields, output_schema, validator)


def json_state(value: Any, input_schema: Any = None) -> Any:
    if input_schema is not None:
        value = (
            input_schema.model_validate_json(value) if isinstance(value, str) else input_schema.model_validate(value)
        )
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json", by_alias=True)
    if not isinstance(value, (str, dict, list)):
        raise ValueError("Jev state must be text, a JSON object, or a JSON array")
    # Fail locally on non-JSON objects and NaN rather than silently stringifying them.
    json.dumps(value, allow_nan=False)
    return value
