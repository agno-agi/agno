"""Keyword-only adapter configuration, including on Python 3.9."""

from dataclasses import dataclass, field
from functools import wraps
from inspect import Parameter, signature
from typing import Any, Type, TypeVar

from typing_extensions import dataclass_transform

_T = TypeVar("_T")


@dataclass_transform(kw_only_default=True, field_specifiers=(field,))
def agent_dataclass(cls: Type[_T]) -> Type[_T]:
    """Provide keyword-only dataclass constructors on Python 3.9.

    Replace this with dataclass(kw_only=True) when Python 3.9 support is dropped.
    The signature and transform expose the same keyword-only API to inspection
    and static type checkers; construction adds one wrapper call.
    """
    cls = dataclass(cls)
    original = cls.__init__

    @wraps(original)
    def init(self: Any, **kwargs: Any) -> None:
        original(self, **kwargs)

    parameters = list(signature(original).parameters.values())
    setattr(
        init,
        "__signature__",
        signature(original).replace(
            parameters=[
                parameters[0],
                *(param.replace(kind=Parameter.KEYWORD_ONLY) for param in parameters[1:]),
            ]
        ),
    )
    setattr(cls, "__init__", init)
    return cls
