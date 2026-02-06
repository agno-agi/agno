import inspect
from collections import defaultdict

from agno.agent.agent import Agent

# Explicitly allow known intentional collisions here if needed.
ALLOWED_PUBLIC_METHOD_COLLISIONS: dict[str, set[str]] = {}


def _public_methods_defined_on_class(cls: type) -> set[str]:
    methods = set()
    for name, value in cls.__dict__.items():
        if name.startswith("_"):
            continue

        resolved = value.__func__ if isinstance(value, (staticmethod, classmethod)) else value
        if inspect.isfunction(resolved):
            methods.add(name)
    return methods


def test_agent_traits_have_no_public_method_collisions():
    trait_classes = [
        cls
        for cls in Agent.__mro__
        if cls.__module__.startswith("agno.agent.trait.") and cls.__name__.endswith("Trait")
    ]

    method_owners: dict[str, list[str]] = defaultdict(list)
    for trait in trait_classes:
        for method_name in _public_methods_defined_on_class(trait):
            method_owners[method_name].append(trait.__name__)

    collisions = {}
    for method_name, owners in method_owners.items():
        if len(owners) <= 1:
            continue

        owner_set = set(owners)
        if method_name in ALLOWED_PUBLIC_METHOD_COLLISIONS:
            if owner_set == ALLOWED_PUBLIC_METHOD_COLLISIONS[method_name]:
                continue

        collisions[method_name] = sorted(owners)

    assert collisions == {}, (
        "Public trait method collisions detected. "
        "Rename the methods or add an explicit allowlist entry in "
        "ALLOWED_PUBLIC_METHOD_COLLISIONS.\n"
        f"Collisions: {collisions}"
    )
