"""The @approval decorator for marking tools as requiring approval."""

from __future__ import annotations

from typing import Any, Callable, Optional, Union, overload

from agno.approval.types import ApprovalType

# Sentinel attribute stamped on raw callables when @approval is below @tool
_APPROVAL_ATTR = "_agno_approval_type"


@overload
def approval(func_or_type: Callable) -> Any: ...


@overload
def approval(*, type: Union[str, ApprovalType] = ApprovalType.required) -> Callable: ...


def approval(
    func_or_type: Optional[Callable] = None,
    *,
    type: Union[str, ApprovalType] = ApprovalType.required,
) -> Any:
    """Mark a tool as requiring approval.

    Can be used as ``@approval``, ``@approval()``, or ``@approval(type="audit")``.
    Composes with ``@tool()`` in either order.

    When applied on top of ``@tool`` (receives a Function):
        Sets ``approval_type`` on the Function directly.

    When applied below ``@tool`` (receives a raw callable):
        Stamps a sentinel attribute that ``@tool`` detects during processing.

    Args:
        type: Approval type. ``"required"`` (default) creates a blocking approval
              that must be resolved before the run continues. ``"audit"`` creates
              a non-blocking audit record after the HITL interaction resolves.
    """
    from agno.tools.function import Function

    approval_type_str = type.value if isinstance(type, ApprovalType) else type

    if approval_type_str not in ("required", "audit"):
        raise ValueError(f"Invalid approval type: {approval_type_str!r}. Must be 'required' or 'audit'.")

    def _apply(target: Any) -> Any:
        if isinstance(target, Function):
            # @approval is on top of @tool -- Function already exists
            target.approval_type = approval_type_str
            if approval_type_str == "required":
                if not any([target.requires_confirmation, target.requires_user_input, target.external_execution]):
                    target.requires_confirmation = True
            elif approval_type_str == "audit":
                if not any([target.requires_confirmation, target.requires_user_input, target.external_execution]):
                    raise ValueError(
                        "@approval(type='audit') requires at least one HITL flag "
                        "('requires_confirmation', 'requires_user_input', or 'external_execution') "
                        "to be set on @tool()."
                    )
            return target
        elif callable(target):
            # @approval is below @tool (or standalone) -- stamp sentinel
            setattr(target, _APPROVAL_ATTR, approval_type_str)
            return target
        else:
            raise TypeError(f"@approval must be applied to a callable or Function, got {target.__class__.__name__}")

    # @approval (bare, no parens) -- func_or_type IS the function/Function
    if func_or_type is not None and (callable(func_or_type) or isinstance(func_or_type, Function)):
        return _apply(func_or_type)

    # @approval() or @approval(type=...) -- return the decorator
    return _apply
