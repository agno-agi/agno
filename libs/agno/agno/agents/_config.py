"""Keyword-only adapter configuration, including on Python 3.9."""

from dataclasses import dataclass, field
from functools import wraps
from inspect import Parameter, signature
from pathlib import Path
from typing import Any, Type, TypeVar, Union

from typing_extensions import dataclass_transform

_T = TypeVar("_T")


def native_home(path: Union[str, Path]) -> str:
    """Resolve a harness home directory to an absolute path and create it when missing.

    The harness runs as a subprocess with its own working directory, so a relative path
    is resolved against the Python process first. Creating the directory lets a CLI that
    refuses to start without its home (Codex) work on first use.
    """
    resolved = Path(path).expanduser().resolve()
    resolved.mkdir(parents=True, exist_ok=True)
    return str(resolved)


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
