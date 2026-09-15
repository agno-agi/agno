"""Serialized form of a mount's verifiers, shared by Agent, Team and the Verify workflow step."""

import functools
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple, Union

from agno.utils.log import log_warning
from agno.verifiers.base import coerce_verifier, is_async_callable, validate_required_stop_on_failure
from agno.verifiers.fingerprints import require_sync_fingerprint
from agno.verifiers.scorer import ScorerVerifier
from agno.verifiers.shell import ShellVerifier
from agno.verifiers.types import VerificationConfig

if TYPE_CHECKING:
    from agno.registry import Registry
    from agno.verifiers.base import Verifier

# Registry key prefix for verifier checks, so a check does not shadow a same-named executor.
CHECK_REGISTRY_PREFIX = "verify:"


def verifier_to_dict(verifier: Any) -> Dict[str, Any]:
    """One check's serialized form: name and policy, plus the data a ShellVerifier rebuilds
    from; a ScorerVerifier or protocol object carries only its kind."""
    data: Dict[str, Any] = {
        "name": getattr(verifier, "name", "") or "verifier",
        "required": bool(getattr(verifier, "required", True)),
        "max_retries": int(getattr(verifier, "max_retries", 0) or 0),
        "stop_on_failure": bool(getattr(verifier, "stop_on_failure", False)),
    }
    inner = getattr(verifier, "inner", None)
    if isinstance(inner, ShellVerifier):
        data["type"] = "shell"
        # Env values may be secrets; only the key names ride along.
        data["shell"] = {
            "command": inner.command,
            "cwd": inner.cwd,
            "timeout": inner.timeout,
            "env_keys": sorted(inner.env) if inner.env else None,
            "inherit_env": inner.inherit_env,
        }
    elif inner is not None:
        data["type"] = "scorer" if isinstance(inner, ScorerVerifier) else "protocol"
    return data


def shell_from_dict(
    name: str, shell: Dict[str, Any], policy: Dict[str, Any], label: str = "Verify check"
) -> ShellVerifier:
    env_keys = shell.get("env_keys") or []
    if env_keys:
        log_warning(
            f"{label} {name!r} was saved with env keys {env_keys}; env values do not serialize, "
            "so the restored command runs without them"
        )
    return ShellVerifier(
        shell["command"],
        cwd=shell.get("cwd"),
        timeout=shell.get("timeout", 120.0),
        inherit_env=bool(shell.get("inherit_env", True)),
        name=name,
        required=bool(policy.get("required", True)),
        max_retries=int(policy.get("max_retries", 0) or 0),
        stop_on_failure=bool(policy.get("stop_on_failure", False)),
    )


def verifiers_from_dict(
    entries: Any,
    registry: Optional["Registry"] = None,
    strict: bool = False,
    label: str = "Verify check",
) -> List[Any]:
    """Rebuild a mount's coerced verifiers from their serialized form.

    Check callables come back through the registry by name; the serialized per-check
    policy (required/max_retries/stop_on_failure) is re-applied to each rehydrated wrapper. A ``run_condition``
    predicate is a callable and does not round-trip: a restored check runs on every
    attempt. A ShellVerifier rebuilds from its serialized command. A registry miss raises
    under strict; otherwise it degrades to a placeholder whose failure keeps the gate
    closed rather than silently ungating the mount.
    """
    from agno.workflow.step import unresolvable_callable_placeholder

    raw: List[Any] = []
    policies: List[Optional[Dict[str, Any]]] = []
    placeholders: List[int] = []
    for verifier_data in entries or []:
        policy: Optional[Dict[str, Any]] = verifier_data if isinstance(verifier_data, dict) else None
        verifier_name = (policy.get("name") if policy else None) or "verifier"
        kind = policy.get("type") if policy else None
        if kind == "shell" and policy and isinstance(policy.get("shell"), dict):
            raw.append(shell_from_dict(verifier_name, policy["shell"], policy, label))
            policies.append(None)
            continue
        policies.append(policy)
        # Checks register under a prefixed key; a bare-name entry is a function the
        # user registered by hand.
        fn = None
        if registry:
            fn = registry.get_function(CHECK_REGISTRY_PREFIX + verifier_name) or registry.get_function(verifier_name)
        if fn is None:
            if kind in ("scorer", "protocol"):
                message = (
                    f"{label} {verifier_name!r} is a {kind} verifier and cannot be rebuilt from its "
                    "serialized form; register a check under this name to restore it"
                )
            elif registry:
                message = f"{label} '{verifier_name}' not found in registry"
            else:
                message = f"Registry required to deserialize {label} '{verifier_name}'"
            if strict:
                from agno.exceptions import ComponentRehydrationError

                raise ComponentRehydrationError(message)
            log_warning(message)
            fn = unresolvable_callable_placeholder(label, verifier_name)
            fn.__name__ = verifier_name  # type: ignore
            placeholders.append(len(raw))
        raw.append(fn)

    verifiers = [coerce_verifier(entry) for entry in raw]
    # Coercion read policy off the raw callables, which carry none; the serialized
    # policy is re-applied to the coerced wrappers, where the run loop reads it.
    for wrapper, policy in zip(verifiers, policies):
        if policy is None:
            continue
        # A registry adapter carries the prefixed key as its name; the check keeps
        # the name it was saved under.
        wrapper.name = str(policy.get("name") or getattr(wrapper, "name", "verifier"))  # type: ignore
        wrapper.required = bool(policy.get("required", True))  # type: ignore
        wrapper.max_retries = int(policy.get("max_retries", 0) or 0)  # type: ignore
        wrapper.stop_on_failure = bool(policy.get("stop_on_failure", False))  # type: ignore
        validate_required_stop_on_failure(
            bool(policy.get("required", True)),
            bool(policy.get("stop_on_failure", False)),
            label=f"{label} {getattr(wrapper, 'name', 'check')!r}",
        )
    for index in placeholders:
        wrapper = verifiers[index]
        # A placeholder can never pass; re-running against it would only spend the
        # attempt budget, so a required one ends the gate on its first failure.
        if getattr(wrapper, "required", True):
            wrapper.stop_on_failure = True  # type: ignore
    return verifiers


def verification_config_to_dict(config: VerificationConfig) -> Dict[str, Any]:
    # The fingerprint is a live object and does not serialize.
    return {
        "max_attempts": config.max_attempts,
        "timeout": config.timeout,
        "stop_on_unchanged_state": config.stop_on_unchanged_state,
        "add_verification_to_context": config.add_verification_to_context,
    }


def warn_stop_on_unchanged_state_not_restored(class_name: str, label: str) -> None:
    log_warning(
        f"{class_name}.from_dict: stop_on_unchanged_state is off for {label} because its fingerprint does not serialize"
    )


def verification_config_from_dict(data: Dict[str, Any], label: str) -> VerificationConfig:
    if data.get("stop_on_unchanged_state"):
        warn_stop_on_unchanged_state_not_restored("VerificationConfig", label)
    return VerificationConfig(
        max_attempts=data.get("max_attempts", 3),
        timeout=data.get("timeout"),
        stop_on_unchanged_state=False,
        fingerprint=None,
        add_verification_to_context=bool(data.get("add_verification_to_context", True)),
    )


def registrable_verify_check(coerced: Any) -> Optional[Any]:
    """The callable to register for one coerced check, or None.

    A check serializes as its verifier name, and rehydration resolves that name
    through ``registry.get_function`` - which matches on ``__name__`` - under the
    ``verify:`` prefix, so a check never shares a registry key with a same-named
    step executor, evaluator or selector. A delegating adapter carries the prefixed
    name plus the mount's policy attributes, with ``__wrapped__`` preserving the
    original signature for by-name argument routing. Protocol objects without a
    callable target return None - the fail-closed rehydration placeholder covers them.
    """
    emitted = CHECK_REGISTRY_PREFIX + (getattr(coerced, "name", "") or "verifier")
    target = getattr(coerced, "fn", None)
    if target is None:
        # A protocol object cannot be re-routed through a plain function
        # adapter without losing its verify and averify methods.
        return None
    if not callable(target):
        return None
    if is_async_callable(target):

        async def adapter(*args: Any, **kwargs: Any) -> Any:
            return await target(*args, **kwargs)
    else:

        def adapter(*args: Any, **kwargs: Any) -> Any:  # type: ignore
            return target(*args, **kwargs)

    adapter = functools.wraps(target)(adapter)
    adapter.__name__ = emitted
    adapter.__qualname__ = emitted
    for attr in ("required", "max_retries", "run_condition", "stop_on_failure"):
        if hasattr(coerced, attr):
            setattr(adapter, attr, getattr(coerced, attr))
    return adapter


def register_verify_checks(verifiers: Any, registry: "Registry") -> None:
    """Register a mount's coerced checks so they resolve by name at rehydration."""
    for coerced in verifiers or []:
        registrable = registrable_verify_check(coerced)
        if registrable is None:
            continue
        existing = registry.get_function(registrable.__name__)
        if existing is not None and getattr(existing, "__wrapped__", None) is registrable.__wrapped__:
            # The same check mounted twice registers once; a distinct callable
            # under the name is left for add_function to report.
            continue
        registry.add_function(registrable)


def validate_verifiers(
    verifiers: Optional[List[Union["Verifier", Callable[..., Any]]]],
    verification: Optional[Union[bool, VerificationConfig]],
    owner: str,
) -> Tuple[Optional[List[Union["Verifier", Callable[..., Any]]]], Optional[Union[bool, VerificationConfig]]]:
    """Validate the verification settings at construction, so a bad entry fails at build and
    not mid-run, and return the normalized pair: ``verification=True`` becomes the default config."""
    if verifiers is not None and not isinstance(verifiers, (list, tuple)):
        raise TypeError(f"{owner}: verifiers must be a list of callables or Verifiers, got {type(verifiers).__name__}")
    if verification is not None and not isinstance(verification, (bool, VerificationConfig)):
        raise TypeError(
            f"{owner}: verification must be True, False, None or a VerificationConfig, "
            f"got {type(verification).__name__}"
        )
    verifier_list = list(verifiers) if verifiers else None
    for v in verifier_list or []:
        coerce_verifier(v)
    if verification is True:
        verification = VerificationConfig()
    return verifier_list, verification


def resolve_verification(owner: Any) -> Optional[VerificationConfig]:
    """The config an owner's runs are verified under, or None when they are not: no verifiers,
    or ``verification=False``. ``True`` and None both mean the default config."""
    verification = getattr(owner, "verification", None)
    if not getattr(owner, "verifiers", None) or verification is False:
        return None
    return verification if isinstance(verification, VerificationConfig) else VerificationConfig()


def require_sync_verifiers(verifiers: Any, fingerprint: Any = None) -> None:
    """Refuse on `run()` what only `arun()` can drive - an async verifier, an async run_condition
    or an async-only fingerprint - before the run starts, as `run()` refuses an async hook."""
    for entry in verifiers or []:
        coerce_verifier(entry).require_sync()
    if fingerprint is not None:
        require_sync_fingerprint(fingerprint)


def require_sync_verification(owner: Any) -> None:
    """`require_sync_verifiers` for an agent or team whose runs are verified."""
    verification = resolve_verification(owner)
    if verification is not None:
        require_sync_verifiers(owner.verifiers, verification.fingerprint)
