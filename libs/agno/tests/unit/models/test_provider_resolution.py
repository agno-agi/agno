"""Tests for provider-key resolution used when reconstructing models from a serialized dict.

These guard the round-trip ``Model.to_dict() -> get_model_from_dict()`` so that a model loaded
from the database (e.g. the components table) rebuilds as the correct provider class, and so a
single unsupported/misconfigured provider no longer needs special-casing per call site.
"""

import os

import pytest

os.environ.setdefault("OPENAI_API_KEY", "test-key-for-testing")

from agno.models.utils import (
    MODEL_PROVIDER_CLASSES,
    _get_model_class,
    _resolve_provider_key,
    get_model_from_dict,
)

# Providers whose model classes require an optional SDK at construction time. We cannot
# instantiate them in the base test environment, so they are covered by the
# resolution-only test below using their known serialized (provider, name) pairs.
SDK_GATED_KEYS = {
    "aws-bedrock",
    "aws-claude",
    "azure-ai-foundry",
    "cerebras",
    "cerebras-openai",
    "cohere",
    "groq",
    "huggingface",
    "ibm",
    "litellm",
    "litellm-openai",
    "llama-openai",
    "meta",
    "mistral",
    "ollama",
    "ollama-responses",
    "portkey",
}

CONSTRUCTABLE_KEYS = [k for k in MODEL_PROVIDER_CLASSES if k not in SDK_GATED_KEYS]


@pytest.mark.parametrize("key", CONSTRUCTABLE_KEYS)
def test_to_dict_round_trip_preserves_class(key):
    """Every constructable provider rebuilds as the same class through to_dict/from_dict."""
    model = _get_model_class("test-id", key)
    rebuilt = get_model_from_dict(model.to_dict())
    assert type(rebuilt) is type(model)
    assert rebuilt.id == "test-id"


@pytest.mark.parametrize(
    "provider, name, expected_key",
    [
        # The crash from the components table: Azure models all report provider "Azure".
        ("Azure", "AzureOpenAI", "azure-openai"),
        ("Azure", "AzureAIFoundry", "azure-ai-foundry"),
        ("AzureFoundry", "AzureFoundryClaude", "azure-foundry-claude"),
        # SDK-gated providers, validated via their serialized (provider, name) pairs.
        ("AwsBedrock", "AwsBedrock", "aws-bedrock"),
        ("AwsBedrock", "AwsBedrockAnthropicClaude", "aws-claude"),
        ("Cerebras", "Cerebras", "cerebras"),
        ("CerebrasOpenAI", "CerebrasOpenAI", "cerebras-openai"),
        ("Cohere", "cohere", "cohere"),
        ("Groq", "Groq", "groq"),
        ("HuggingFace", "HuggingFace", "huggingface"),
        ("IBM", "WatsonX", "ibm"),
        ("LiteLLM", "LiteLLM", "litellm"),
        ("LiteLLM", "LiteLLMOpenAI", "litellm-openai"),
        ("Llama", "Llama", "meta"),
        ("LlamaOpenAI", "LlamaOpenAI", "llama-openai"),
        ("Mistral", "MistralChat", "mistral"),
        ("Ollama", "Ollama", "ollama"),
        ("Ollama", "OllamaResponses", "ollama-responses"),
        ("Portkey", "Portkey", "portkey"),
    ],
)
def test_resolve_sdk_gated_providers(provider, name, expected_key):
    assert _resolve_provider_key(provider, name) == expected_key


@pytest.mark.parametrize(
    "provider, name, expected_key",
    [
        # Display-string providers that differ from the registry key resolve via alias,
        # including the legacy/string path where no name is serialized.
        ("Azure", None, "azure-openai"),
        ("azure", None, "azure-openai"),
        ("InceptionLabs", None, "inception"),
        ("VertexAI", None, "vertexai-claude"),
        ("LlamaCpp", None, "llama-cpp"),
        ("Xiaomi MiMo", None, "xiaomi"),
        # CometAPI sets provider to "CometAPI (<id>)" via post-init; name still resolves it.
        ("CometAPI (gpt-x)", "CometAPI", "cometapi"),
        # Tuning Engines: provider/name carry a space; both the name and string paths resolve.
        ("Tuning Engines", "Tuning Engines", "tuning-engines"),
        ("Tuning Engines", None, "tuning-engines"),
        # Plain providers whose display string already equals the key.
        ("openai", None, "openai"),
        ("anthropic", None, "anthropic"),
    ],
)
def test_resolve_provider_aliases(provider, name, expected_key):
    assert _resolve_provider_key(provider, name) == expected_key


def test_unsupported_provider_raises():
    with pytest.raises(ValueError, match="is not supported"):
        _get_model_class("some-id", "definitely-not-a-provider")


def test_get_model_from_dict_requires_id():
    with pytest.raises(ValueError, match="missing an 'id'"):
        get_model_from_dict({"provider": "openai"})


# Abstract/intermediate Model subclasses that are not concrete providers and so must not appear
# in MODEL_PROVIDER_CLASSES. Add a class here only after a deliberate decision that it is not a
# user-selectable provider. Keyed by (defining_module, class_name).
_NON_PROVIDER_MODEL_CLASSES = {("agno.models.openai.like", "OpenAILike")}


def _models_root():
    from pathlib import Path

    root = Path(__file__).resolve().parents[3] / "agno" / "models"
    assert root.is_dir(), f"models root not found: {root}"
    return root


def _module_name(path, root):
    name = ".".join(path.relative_to(root.parents[1]).with_suffix("").parts)
    return name[: -len(".__init__")] if name.endswith(".__init__") else name


def _discover_model_subclasses(root):
    """Statically find every concrete Model subclass under agno/models, without importing.

    Parses the source with ``ast`` so SDK-gated providers (whose modules fail to import without
    their optional dependency) are still discovered. Returns a set of (defining_module, class).
    """
    import ast

    # (defining_module, class_name) -> [base names]
    class_bases: dict = {}
    for path in root.rglob("*.py"):
        if path.name == "__init__.py":
            continue  # __init__ only re-exports; concrete classes live in submodules
        module = _module_name(path, root)
        for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
            if isinstance(node, ast.ClassDef):
                bases = [
                    b.id if isinstance(b, ast.Name) else b.attr
                    for b in node.bases
                    if isinstance(b, (ast.Name, ast.Attribute))
                ]
                class_bases[(module, node.name)] = bases

    # Transitively mark every class whose base chain reaches Model (matched by class name, since
    # bases are often imported under aliases and cannot be resolved without importing).
    rooted = {"Model"}
    changed = True
    while changed:
        changed = False
        for (_module, name), bases in class_bases.items():
            if name not in rooted and any(b in rooted for b in bases):
                rooted.add(name)
                changed = True

    return {(module, name) for (module, name), bases in class_bases.items() if name != "Model" and name in rooted}


def _registered_defining_classes(root):
    """Resolve every MODEL_PROVIDER_CLASSES entry to the (defining_module, class) it points at.

    The registry references the re-exporting package and that package's exported name (e.g.
    ``("agno.models.azure", "AzureFoundryClaude")``), while the class is defined in a submodule
    under its own name (``agno.models.azure.claude.Claude``). Parse each package __init__ to
    follow ``from <mod> import <name> as <alias>`` re-exports back to the definition.
    """
    import ast

    # (package_module, exported_name) -> (source_module, source_name)
    reexports: dict = {}
    for path in root.rglob("__init__.py"):
        package = _module_name(path, root)
        for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
            if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                for alias in node.names:
                    reexports[(package, alias.asname or alias.name)] = (node.module, alias.name)

    resolved = set()
    for reg_module, reg_class in MODEL_PROVIDER_CLASSES.values():
        resolved.add(reexports.get((reg_module, reg_class), (reg_module, reg_class)))
    return resolved


def test_every_model_subclass_is_registered():
    """Guard against drift: every concrete provider on disk must be in MODEL_PROVIDER_CLASSES.

    CI fails on the same PR that adds a new Model subclass without a registry entry, so the
    registry stays the single source of truth without per-provider runtime wiring.
    """
    root = _models_root()
    discovered = _discover_model_subclasses(root)
    covered = _registered_defining_classes(root) | _NON_PROVIDER_MODEL_CLASSES

    missing = sorted(f"{name} ({module})" for (module, name) in discovered - covered)
    assert not missing, (
        "Model subclasses missing from MODEL_PROVIDER_CLASSES: "
        + ", ".join(missing)
        + ". Add each to the registry in agno/models/utils.py (or to the test allowlist if it is "
        "not a user-selectable provider)."
    )
