"""Rebuild a deep copy of an Agent, Team or Workflow subclass without its own initializer."""

from dataclasses import fields
from inspect import Parameter, signature
from typing import Any, Callable, Dict, Set


def init_parameter_names(cls: Any) -> Set[str]:
    """The keyword names cls.__init__ declares, without self."""
    return set(signature(cls.__init__).parameters.keys()) - {"self"}


def forwards_init_kwargs(cls: Any, base: Any) -> bool:
    """Whether cls replaces base's initializer with one that takes **kwargs.

    Such an initializer names none of the fields it forwards, so a copy rebuilt
    through it by parameter name comes out blank. Passing every field instead
    breaks a subclass that hardcodes one of them, as in
    super().__init__(name="helper", **kwargs), with a duplicate keyword error.
    """
    init = cls.__init__
    if init is base.__init__:
        return False
    return any(p.kind is Parameter.VAR_KEYWORD for p in signature(init).parameters.values())


def rebuild_through_base_init(
    original: Any,
    base: Any,
    kwargs: Dict[str, Any],
    copy_value: Callable[[str, Any], Any],
) -> Any:
    """Build a new instance of type(original) by running only base.__init__ on it.

    kwargs holds the already copied fields plus any caller update. The ones base
    accepts go to its initializer. Attributes the subclass set on the original
    that are neither dataclass fields nor set by base.__init__ are carried over
    through copy_value, and an update naming one of those replaces it. The
    subclass initializer does not run, so values it derives from its own
    arguments are copied as they are, not recomputed.
    """
    cls: Any = type(original)
    base_params = init_parameter_names(base)
    init_kwargs = {name: value for name, value in kwargs.items() if name in base_params}
    late_updates = {name: value for name, value in kwargs.items() if name not in base_params}

    copied = cls.__new__(cls)
    base.__init__(copied, **init_kwargs)

    field_names = {f.name for f in fields(original)}
    set_by_base = set(vars(copied))
    own_attributes = {
        name: value for name, value in vars(original).items() if name not in field_names and name not in set_by_base
    }
    for name, value in own_attributes.items():
        setattr(copied, name, copy_value(name, value))

    for name, value in late_updates.items():
        if name not in own_attributes:
            raise TypeError(f"{cls.__name__}.deep_copy() got an unexpected field '{name}'")
        setattr(copied, name, value)

    return copied
