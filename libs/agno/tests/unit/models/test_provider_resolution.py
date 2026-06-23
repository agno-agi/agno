"""Tests for provider-key resolution used when reconstructing models from a serialized dict.

These guard the round-trip ``Model.to_dict() -> get_model_from_dict()`` so that a model loaded
from the database (e.g. the components table) rebuilds as the correct provider class, and so a
single unsupported/misconfigured provider no longer needs special-casing per call site.
"""

import os

import pytest

os.environ.setdefault("OPENAI_API_KEY", "test-key-for-testing")

from agno.models.base import Model
from agno.models.utils import (
    MODEL_PROVIDER_CLASSES,
    _canonical_provider_display,
    _get_model_class,
    _resolve_provider_key,
    get_model_from_dict,
    resolve_model,
)

ALL_PROVIDER_KEYS = sorted(MODEL_PROVIDER_CLASSES)


def _construct_or_skip(key):
    """Construct a provider's model, or skip if its optional SDK is not installed.

    The base test env (the ``dev`` extra) ships only the ``openai`` SDK, while the demo env ships
    all of them. Skipping on ImportError keeps these tests correct in any environment instead of
    hardcoding which providers are installable; resolution itself (no construction) is covered for
    every provider by the parametrized resolution tests below.
    """
    try:
        return _get_model_class("test-id", key)
    except ImportError as e:
        pytest.skip(f"optional SDK for '{key}' not installed: {e}")


@pytest.mark.parametrize("key", ALL_PROVIDER_KEYS)
def test_to_dict_round_trip_preserves_class(key):
    """Every installable provider rebuilds as the same class through to_dict/from_dict."""
    model = _construct_or_skip(key)
    rebuilt = get_model_from_dict(model.to_dict())
    assert type(rebuilt) is type(model)
    assert rebuilt.id == "test-id"


def test_to_dict_serializes_non_secret_connection_params_not_credentials():
    """to_dict round-trips declared connection params (azure_endpoint, ...) but never credentials."""
    from agno.models.azure import AzureOpenAI

    model = AzureOpenAI(
        id="gpt-4.1-mini",
        api_key="super-secret",
        api_version="2024-12-01-preview",
        azure_endpoint="https://example.cognitiveservices.azure.com",
        azure_deployment="my-deployment",
    )
    data = model.to_dict()

    assert data["azure_endpoint"] == "https://example.cognitiveservices.azure.com"
    assert data["api_version"] == "2024-12-01-preview"
    assert data["azure_deployment"] == "my-deployment"
    # Credentials must never be persisted.
    assert "api_key" not in data
    assert "azure_ad_token" not in data


def test_get_model_from_dict_recovers_connection_params():
    """Rebuilding from a dict restores the non-secret connection params (self-healing fallback)."""
    from agno.models.azure import AzureOpenAI

    rebuilt = get_model_from_dict(
        {
            "id": "gpt-4.1-mini",
            "name": "AzureOpenAI",
            "provider": "Azure",
            "azure_endpoint": "https://example.cognitiveservices.azure.com",
            "api_version": "2024-12-01-preview",
        }
    )
    assert isinstance(rebuilt, AzureOpenAI)
    assert rebuilt.azure_endpoint == "https://example.cognitiveservices.azure.com"
    assert rebuilt.api_version == "2024-12-01-preview"


def test_get_model_from_dict_ignores_undeclared_params():
    """Only fields a class declares serializable are passed to its constructor."""
    from agno.models.openai import OpenAIResponses

    # base_url is declared; a stray non-serializable field must be dropped, not injected.
    rebuilt = get_model_from_dict(
        {
            "id": "gpt-5.5",
            "name": "OpenAIResponses",
            "provider": "OpenAI",
            "base_url": "https://proxy.example.com/v1",
            "api_key": "should-be-ignored",
        }
    )
    assert isinstance(rebuilt, OpenAIResponses)
    assert str(rebuilt.base_url) == "https://proxy.example.com/v1"
    assert rebuilt.api_key != "should-be-ignored"


@pytest.mark.parametrize("key", ALL_PROVIDER_KEYS)
def test_canonical_provider_display_matches_class(key):
    """Drift guard: the provider-display override table matches what each class actually reports.

    Keeps name-vs-provider disambiguation correct if a provider's display string ever changes.
    """
    model = _construct_or_skip(key)
    assert _canonical_provider_display(key) == (model.provider or "").strip().lower()


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
        # Anthropic-backed providers (anthropic SDK not in base test env).
        ("Anthropic", "Claude", "anthropic"),
        ("AzureFoundry", "AzureFoundryClaude", "azure-foundry-claude"),
        ("VertexAI", "Claude", "vertexai-claude"),
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
        # CometAPI inherits provider "OpenAI" from OpenAILike; its name disambiguates it.
        ("OpenAI", "CometAPI", "cometapi"),
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


@pytest.mark.parametrize(
    "provider, name, expected_key",
    [
        # A user-supplied name that collides with another provider's default name must NOT
        # override the provider string. The name only disambiguates within the same family.
        ("OpenAI", "Gemini", "openai"),
        ("OpenAI", "Groq", "openai"),
        ("Groq", "Gemini", "groq"),
        ("Anthropic", "OpenAIChat", "anthropic"),
        # Within-family disambiguation still works (these share a display provider string).
        ("OpenAI", "OpenAIChat", "openai-chat"),
        # "OpenAIResponses" is the default name for both the "openai" and "openai-responses" keys
        # (same class), so it resolves to the canonical "openai" key -- still the OpenAIResponses class.
        ("OpenAI", "OpenAIResponses", "openai"),
        ("Azure", "AzureAIFoundry", "azure-ai-foundry"),
    ],
)
def test_name_does_not_override_conflicting_provider(provider, name, expected_key):
    assert _resolve_provider_key(provider, name) == expected_key


def test_user_named_model_reconstructs_correct_provider():
    """Regression: OpenAIChat(name="Gemini") must not rebuild as the Google Gemini class."""
    pytest.importorskip("openai")  # openai is an optional extra, not a base dependency
    rebuilt = get_model_from_dict({"provider": "OpenAI", "name": "Gemini", "id": "gpt-4o"})
    assert type(rebuilt).__name__ != "Gemini"
    assert rebuilt.provider == "OpenAI"


@pytest.mark.parametrize(
    "provider, name",
    [
        ("my-gateway", "Gemini"),  # unknown provider must not be re-routed by a colliding name
        ("totally-custom", "OpenAIChat"),
    ],
)
def test_unrecognized_provider_not_overridden_by_name(provider, name):
    """A non-empty unsupported provider stays authoritative and is rejected, not name-routed."""
    assert _resolve_provider_key(provider, name) == provider
    with pytest.raises(ValueError, match="is not supported"):
        get_model_from_dict({"provider": provider, "name": name, "id": "x"})


def test_empty_provider_falls_back_to_name():
    """With no provider string, the serialized name is the only signal and is used."""
    assert _resolve_provider_key("", "Groq") == "groq"
    assert _resolve_provider_key(None, "OpenAIChat") == "openai-chat"


def test_unsupported_provider_raises():
    with pytest.raises(ValueError, match="is not supported"):
        _get_model_class("some-id", "definitely-not-a-provider")


def test_get_model_from_dict_requires_id():
    with pytest.raises(ValueError, match="missing an 'id'"):
        get_model_from_dict({"provider": "openai"})


class _FakeRegistry:
    """Minimal registry stub exposing get_model() the way Registry does."""

    def __init__(self, model):
        self._model = model

    def get_model(self, model_id, provider=None, name=None, params=None):
        if self._model is None or getattr(self._model, "id", None) != model_id:
            return None
        if provider is not None and getattr(self._model, "provider", None) != provider:
            return None
        if name is not None and getattr(self._model, "name", None) != name:
            return None
        if params and any(getattr(self._model, key, None) != value for key, value in params.items()):
            return None
        return self._model


def test_resolve_model_prefers_registry_instance():
    """A dict that matches a registered model resolves to the live instance, not a rebuild."""

    class _M:
        id = "gpt-5.5"
        provider = "OpenAI"
        name = "OpenAIResponses"

    live = _M()
    registry = _FakeRegistry(live)

    resolved = resolve_model({"id": "gpt-5.5", "provider": "OpenAI", "name": "OpenAIResponses"}, registry)
    assert resolved is live


def test_resolve_model_falls_back_to_dict_when_not_registered():
    """When the registry has no match, resolve_model rebuilds from the dict (unchanged behavior)."""
    registry = _FakeRegistry(None)
    rebuilt = resolve_model({"id": "gpt-4o", "provider": "OpenAI", "name": "OpenAIResponses"}, registry)
    assert isinstance(rebuilt, Model)
    assert rebuilt.id == "gpt-4o"


def test_resolve_model_without_registry_rebuilds_from_dict():
    rebuilt = resolve_model({"id": "gpt-4o", "provider": "OpenAI", "name": "OpenAIResponses"})
    assert isinstance(rebuilt, Model)
    assert rebuilt.id == "gpt-4o"


def test_resolve_model_from_string():
    rebuilt = resolve_model("openai:gpt-4o")
    assert isinstance(rebuilt, Model)
    assert rebuilt.id == "gpt-4o"


def test_resolve_model_passes_through_unhandled_values():
    """Values that are neither a model dict nor a string are returned unchanged."""
    sentinel = object()
    assert resolve_model(sentinel) is sentinel
    assert resolve_model({"no": "id"}) == {"no": "id"}


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
