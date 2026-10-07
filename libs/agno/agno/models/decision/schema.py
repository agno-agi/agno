from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from inspect import cleandoc
from typing import Any, Dict, Literal, Mapping, Optional, Type, Union, get_args, get_origin

from pydantic import BaseModel
from pydantic.fields import FieldInfo

from agno.models.decision.types import (
    BinaryAnswer,
    BinaryQuestion,
    Choice,
    ChoiceAnswer,
    Noul,
    RefusalAnswer,
    Score,
    ScoreAnswer,
)
from agno.utils.schema import is_union

QuestionType = Union[BinaryQuestion, Choice, Score]

_Kind = Literal["bool", "literal", "enum", "int", "float"]


@dataclass(frozen=True)
class FieldQuestion:
    """How one output_schema field is asked and how its answer is read back."""

    question: QuestionType
    kind: _Kind
    optional: bool
    enum_type: Optional[Type[Enum]] = None


def questions_from_schema(schema: Type[BaseModel]) -> Dict[str, QuestionType]:
    """The questions a decision model answers to fill `schema`, one per field."""
    return {name: plan.question for name, plan in plan_schema(schema).items()}


def plan_schema(schema: Type[BaseModel]) -> Dict[str, FieldQuestion]:
    """Map every field of `schema` to a question. Raises ValueError naming the first unsupported field."""
    if not (isinstance(schema, type) and issubclass(schema, BaseModel)):
        raise ValueError("A decision model needs `output_schema` to be a pydantic BaseModel class")
    return _plan_schema(schema)


@lru_cache(maxsize=256)
def _plan_schema(schema: Type[BaseModel]) -> Dict[str, FieldQuestion]:
    if not schema.model_fields:
        raise ValueError(f"output_schema {schema.__name__} has no fields")
    goal = cleandoc(schema.__doc__) if schema.__doc__ else None
    return {name: _plan_field(schema.__name__, name, field, goal) for name, field in schema.model_fields.items()}


def build_output(schema: Type[BaseModel], answers: Mapping[str, Any]) -> BaseModel:
    """Build the schema instance from decision answers, running its validators."""
    values: Dict[str, Any] = {}
    for name, plan in plan_schema(schema).items():
        answer = answers[name]
        if isinstance(answer, RefusalAnswer):
            if not plan.optional:
                raise ValueError(f"The decision model declined to answer '{name}', which is not Optional")
            values[name] = None
        elif plan.kind == "bool" and isinstance(answer, BinaryAnswer):
            values[name] = answer.value
        elif plan.kind == "literal" and isinstance(answer, ChoiceAnswer):
            values[name] = answer.value
        elif plan.kind == "enum" and isinstance(answer, ChoiceAnswer) and plan.enum_type is not None:
            values[name] = plan.enum_type(answer.value)
        elif plan.kind == "int" and isinstance(answer, ScoreAnswer):
            values[name] = answer.level
        elif plan.kind == "float" and isinstance(answer, ScoreAnswer):
            values[name] = answer.value
        else:
            raise ValueError(f"Answer for '{name}' does not match its field type: {answer}")
    return schema(**values)


def _plan_field(schema_name: str, name: str, field: FieldInfo, goal: Optional[str]) -> FieldQuestion:
    where = f"{schema_name}.{name}"
    annotation, optional = _unwrap_optional(field.annotation)
    markers = [m for m in field.metadata if isinstance(m, (BinaryQuestion, Choice, Score))]
    if len(markers) > 1:
        raise ValueError(f"{where} has more than one question annotation")
    marker = markers[0] if markers else None
    instructions = _instructions(name, field, marker, goal)

    if annotation is bool:
        if marker is not None and not isinstance(marker, BinaryQuestion):
            raise ValueError(f"{where} is a bool, so it takes Noul or Predicate, not {type(marker).__name__}")
        question = _rebuild(marker or Noul(), instructions=instructions)
        return FieldQuestion(question=question, kind="bool", optional=optional)

    if get_origin(annotation) is Literal:
        literal_values = list(get_args(annotation))
        if not all(isinstance(v, str) for v in literal_values):
            raise ValueError(f"{where} must be a Literal of strings")
        return FieldQuestion(
            question=_choice(where, marker, instructions, literal_values), kind="literal", optional=optional
        )

    if isinstance(annotation, type) and issubclass(annotation, Enum):
        values = [member.value for member in annotation]
        if not all(isinstance(v, str) for v in values):
            raise ValueError(f"{where} must be an Enum with string values")
        return FieldQuestion(
            question=_choice(where, marker, instructions, values),
            kind="enum",
            optional=optional,
            enum_type=annotation,
        )

    if annotation in (int, float):
        if not isinstance(marker, Score) or marker.levels is None:
            raise ValueError(f"{where} is a number, so it needs Annotated[..., Score(levels=[...])]")
        question = _rebuild(marker, instructions=instructions)
        return FieldQuestion(question=question, kind="int" if annotation is int else "float", optional=optional)

    raise ValueError(
        f"{where} has type {annotation!r}, which a decision model cannot fill. "
        "Use bool, a Literal of strings, a string Enum, or an int/float with Score(levels=[...])"
    )


def _choice(where: str, marker: Optional[QuestionType], instructions: str, values: list) -> Choice:
    if marker is not None and not isinstance(marker, Choice):
        raise ValueError(f"{where} has fixed options, so it takes Choice, not {type(marker).__name__}")
    if marker is not None and marker.options is not None:
        if set(marker.options) != set(values):
            raise ValueError(f"{where}: Choice options {sorted(marker.options)} do not match the field's values")
        options: Dict[str, Optional[str]] = {v: marker.options[v] for v in values}
    else:
        options = {v: None for v in values}
    return Choice(instructions=instructions, options=options)


def _rebuild(question: QuestionType, **updates: Any) -> QuestionType:
    data = question.model_dump(exclude_none=True)
    data.update(updates)
    return type(question)(**data)


def _instructions(name: str, field: FieldInfo, marker: Optional[QuestionType], goal: Optional[str]) -> str:
    instructions = (marker.instructions if marker is not None else None) or field.description
    if not instructions:
        instructions = name.replace("_", " ")
    return f"{goal}\n{instructions}" if goal else instructions


def _unwrap_optional(annotation: Any) -> tuple:
    if is_union(annotation):
        args = [a for a in get_args(annotation) if a is not type(None)]
        if len(args) == 1:
            return args[0], True
    return annotation, False
