from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Literal, Mapping, Optional, Union

from pydantic import BaseModel, Field, field_validator, model_validator
from typing_extensions import Annotated

from agno.metrics import MessageMetrics


def _to_described(value: Any, kind: str) -> Any:
    """Normalize a list of names into a name -> description mapping, rejecting duplicates."""
    if isinstance(value, (list, tuple)):
        if len(set(value)) != len(value):
            raise ValueError(f"{kind} must be unique")
        return {name: None for name in value}
    return value


class Noul(BaseModel):
    """A yes/no question. The answer is the probability that the statement is true."""

    type: Literal["noul"] = "noul"
    instructions: str
    yes: Optional[str] = Field(default=None, description="What a yes means")
    no: Optional[str] = Field(default=None, description="What a no means")
    threshold: float = Field(default=0.5, gt=0, lt=1, description="Probability at or above which the answer is yes")

    @model_validator(mode="after")
    def _check_criteria(self) -> "Noul":
        if (self.yes is None) != (self.no is None):
            raise ValueError("Noul needs both `yes` and `no`, or neither")
        return self


class Choice(BaseModel):
    """Pick one of a fixed set of options. Options map each value to an optional description."""

    type: Literal["choice"] = "choice"
    instructions: str
    options: Dict[str, Optional[str]]

    @field_validator("options", mode="before")
    @classmethod
    def _normalize_options(cls, value: Any) -> Any:
        return _to_described(value, "Choice options")

    @field_validator("options")
    @classmethod
    def _check_options(cls, value: Dict[str, Optional[str]]) -> Dict[str, Optional[str]]:
        if len(value) < 2:
            raise ValueError("Choice needs at least 2 options")
        return value


class Score(BaseModel):
    """Rate on an ordered scale. Levels map each label to an optional description, lowest first."""

    type: Literal["score"] = "score"
    instructions: str
    levels: Dict[str, Optional[str]]

    @field_validator("levels", mode="before")
    @classmethod
    def _normalize_levels(cls, value: Any) -> Any:
        return _to_described(value, "Score levels")

    @field_validator("levels")
    @classmethod
    def _check_levels(cls, value: Dict[str, Optional[str]]) -> Dict[str, Optional[str]]:
        if not 2 <= len(value) <= 10:
            raise ValueError("Score needs between 2 and 10 levels")
        return value


Question = Annotated[Union[Noul, Choice, Score], Field(discriminator="type")]


class NoulAnswer(BaseModel):
    type: Literal["noul"] = "noul"
    probability: float
    value: bool


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


Answer = Annotated[Union[NoulAnswer, ChoiceAnswer, ScoreAnswer, RefusalAnswer], Field(discriminator="type")]

State = Union[str, Dict[str, Any], List[str]]


@dataclass
class DecisionResult(Mapping[str, Any]):
    """Answers keyed by question name. Reads like a dict: result["urgent"].probability."""

    answers: Dict[str, Union[NoulAnswer, ChoiceAnswer, ScoreAnswer, RefusalAnswer]]
    model: Optional[str] = None
    metrics: Optional[MessageMetrics] = None
    raw: Optional[Dict[str, Any]] = field(default=None, repr=False)

    def __getitem__(self, name: str) -> Union[NoulAnswer, ChoiceAnswer, ScoreAnswer, RefusalAnswer]:
        return self.answers[name]

    def __iter__(self) -> Iterator[str]:
        return iter(self.answers)

    def __len__(self) -> int:
        return len(self.answers)
