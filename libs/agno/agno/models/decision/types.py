from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Literal, Mapping, Optional, Union

from pydantic import BaseModel, Field, TypeAdapter, field_validator, model_validator
from typing_extensions import Annotated

from agno.metrics import MessageMetrics


def _to_described(value: Any, kind: str) -> Any:
    """Normalize a list of names into a name -> description mapping, rejecting duplicates."""
    if isinstance(value, (list, tuple)):
        if len(set(value)) != len(value):
            raise ValueError(f"{kind} must be unique")
        return {name: None for name in value}
    return value


class _InertWhenAnnotated:
    """Lets a question instance sit in `Annotated[...]` metadata without pydantic using it as the field's schema.

    Pydantic builds a field's schema from any metadata object that has `__get_pydantic_core_schema__`, and a model
    instance inherits it from its class. Instances pass the field's own type through; the class keeps BaseModel's.
    """

    def __get__(self, obj: Any, objtype: Any = None) -> Any:
        if obj is None:
            return BaseModel.__dict__["__get_pydantic_core_schema__"].__get__(objtype, objtype)
        return lambda source, handler: handler(source)


class BinaryQuestion(BaseModel):
    """Fields shared by Noul and Predicate. Every provider accepts both."""

    instructions: Optional[str] = None
    yes: Optional[str] = Field(default=None, description="What a yes means")
    no: Optional[str] = Field(default=None, description="What a no means")
    threshold: float = Field(default=0.5, gt=0, lt=1, description="Probability at or above which the answer is yes")

    __get_pydantic_core_schema__ = _InertWhenAnnotated()  # type: ignore[assignment]

    @model_validator(mode="after")
    def _check_criteria(self) -> "BinaryQuestion":
        if (self.yes is None) != (self.no is None):
            raise ValueError(f"{type(self).__name__} needs both `yes` and `no`, or neither")
        return self

    def answer(self, probability: float) -> "BinaryAnswer":
        raise NotImplementedError


class Noul(BinaryQuestion):
    """A yes/no question, in TypeSafe's terms. Same as Predicate."""

    type: Literal["noul"] = "noul"

    def answer(self, probability: float) -> "NoulAnswer":
        return NoulAnswer(probability=probability, value=probability >= self.threshold)


class Predicate(BinaryQuestion):
    """A statement to check as true or false, in OpenAI's terms. Same as Noul."""

    type: Literal["predicate"] = "predicate"

    def answer(self, probability: float) -> "PredicateAnswer":
        return PredicateAnswer(probability=probability, value=probability >= self.threshold)


class Choice(BaseModel):
    """Pick one of a fixed set of options. Options map each value to an optional description."""

    type: Literal["choice"] = "choice"
    instructions: Optional[str] = None
    options: Optional[Dict[str, Optional[str]]] = None

    __get_pydantic_core_schema__ = _InertWhenAnnotated()  # type: ignore[assignment]

    @field_validator("options", mode="before")
    @classmethod
    def _normalize_options(cls, value: Any) -> Any:
        return _to_described(value, "Choice options")

    @field_validator("options")
    @classmethod
    def _check_options(cls, value: Optional[Dict[str, Optional[str]]]) -> Optional[Dict[str, Optional[str]]]:
        if value is not None and len(value) < 2:
            raise ValueError("Choice needs at least 2 options")
        return value


class Score(BaseModel):
    """Rate on an ordered scale. Levels map each label to an optional description, lowest first."""

    type: Literal["score"] = "score"
    instructions: Optional[str] = None
    levels: Optional[Dict[str, Optional[str]]] = None

    __get_pydantic_core_schema__ = _InertWhenAnnotated()  # type: ignore[assignment]

    @field_validator("levels", mode="before")
    @classmethod
    def _normalize_levels(cls, value: Any) -> Any:
        return _to_described(value, "Score levels")

    @field_validator("levels")
    @classmethod
    def _check_levels(cls, value: Optional[Dict[str, Optional[str]]]) -> Optional[Dict[str, Optional[str]]]:
        if value is not None and not 2 <= len(value) <= 10:
            raise ValueError("Score needs between 2 and 10 levels")
        return value


Question = Annotated[Union[Noul, Predicate, Choice, Score], Field(discriminator="type")]


class BinaryAnswer(BaseModel):
    probability: float
    value: bool


class NoulAnswer(BinaryAnswer):
    type: Literal["noul"] = "noul"


class PredicateAnswer(BinaryAnswer):
    type: Literal["predicate"] = "predicate"


class ChoiceAnswer(BaseModel):
    type: Literal["choice"] = "choice"
    value: str
    probabilities: Dict[str, float]
    confidence: Optional[float] = None


class ScoreAnswer(BaseModel):
    type: Literal["score"] = "score"
    value: float = Field(description="Probability-weighted level index")
    level: int = Field(description="Index of the most likely level")
    label: str = Field(description="Label of the most likely level")
    probabilities: Dict[str, float] = Field(description="Probability per level label")
    confidence: Optional[float] = None


class RefusalAnswer(BaseModel):
    """The provider declined to answer this question."""

    type: Literal["refusal"] = "refusal"
    value: None = None


Answer = Annotated[
    Union[NoulAnswer, PredicateAnswer, ChoiceAnswer, ScoreAnswer, RefusalAnswer], Field(discriminator="type")
]

State = Union[str, Dict[str, Any], List[str]]

_answer_adapter: TypeAdapter = TypeAdapter(Answer)


def answers_to_dict(answers: Mapping[str, Any]) -> Dict[str, Any]:
    """Serialize answers for storage; values that are already dicts pass through."""
    return {name: a.model_dump() if isinstance(a, BaseModel) else a for name, a in answers.items()}


def answers_from_dict(data: Mapping[str, Any]) -> Dict[str, Any]:
    """Rebuild typed answers from `answers_to_dict` output."""
    return {name: a if isinstance(a, BaseModel) else _answer_adapter.validate_python(a) for name, a in data.items()}


@dataclass
class DecisionResult(Mapping[str, Any]):
    """Answers keyed by question name. Reads like a dict: result["urgent"].probability."""

    answers: Dict[str, Union[BinaryAnswer, ChoiceAnswer, ScoreAnswer, RefusalAnswer]]
    model: Optional[str] = None
    metrics: Optional[MessageMetrics] = None
    raw: Optional[Dict[str, Any]] = field(default=None, repr=False)

    def __getitem__(self, name: str) -> Union[BinaryAnswer, ChoiceAnswer, ScoreAnswer, RefusalAnswer]:
        return self.answers[name]

    def __iter__(self) -> Iterator[str]:
        return iter(self.answers)

    def __len__(self) -> int:
        return len(self.answers)
