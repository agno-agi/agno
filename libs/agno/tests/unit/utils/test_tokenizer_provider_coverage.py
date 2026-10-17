"""Item (4) of agno-agi/agno#9993: tokenizer coverage over every provider.

`count_tokens()` falls back to OpenAI's ``o200k_base`` estimate for any model
id the tokenizer mapping does not know. That fallback is now announced
(see agno-agi/agno#10008), but a newly added provider would still slip into
it without anyone noticing. This test enumerates every concrete provider
under ``agno.models`` and requires a conscious tokenizer decision for each:

- the provider overrides ``count_tokens``, or
- its default model id is covered by the family mapping
  (``is_family_mapped``), or
- it is pinned in ``KNOWN_ESTIMATED_TOKENIZER_DEFAULTS`` below, with the
  exact default id it was reviewed at.

A new provider fails this test until one of the three happens; changing a
recorded default id fails too. Entries that become covered must be removed
again, so the record only ever lists genuine estimates.
"""

import importlib
import pkgutil
from dataclasses import MISSING, fields
from typing import Dict, List, Optional, Tuple, Type

import pytest

import agno.models
from agno.models.base import Model
from agno.utils import tokens as tokens_module

# Present once agno-agi/agno#10008 lands; getattr (not a direct reference) so
# this module still imports and type-checks without it.
_is_family_mapped = getattr(tokens_module, "is_family_mapped", None)

requires_tokenizer_mapping = pytest.mark.skipif(
    _is_family_mapped is None,
    reason="needs the per-family tokenizer mapping from agno-agi/agno#10008",
)

# Providers whose default model id has no family tokenizer yet, reviewed at
# the pinned default id. Counts for these are o200k_base estimates (announced
# at runtime). Map the family in HF_TOKENIZER_PATTERNS or override
# count_tokens instead of extending this dict; remove entries that become
# covered.
KNOWN_ESTIMATED_TOKENIZER_DEFAULTS: Dict[str, Optional[str]] = {
    "agno.models.azure.openai_chat.AzureOpenAI": "not-provided",
    "agno.models.dashscope.dashscope.DashScope": "qwen-plus",
    "agno.models.deepseek.deepseek.DeepSeek": "deepseek-v4-flash",
    "agno.models.google.gemini_interactions.GeminiInteractions": "gemini-3.7-flash",
    "agno.models.ibm.watsonx.WatsonX": "ibm/granite-20b-code-instruct",
    "agno.models.inception.inception.Inception": "mercury-2",
    "agno.models.internlm.internlm.InternLM": "internlm2.5-latest",
    "agno.models.llmman.llmman.Llmman": "qwen3:0.6b-q4_K_M",
    "agno.models.lmstudio.lmstudio.LMStudio": "qwen2.5-7b-instruct-1m",
    "agno.models.meta.llama.Llama": "Llama-4-Maverick-17B-128E-Instruct-FP8",
    "agno.models.meta.llama_openai.LlamaOpenAI": "Llama-4-Maverick-17B-128E-Instruct-FP8",
    "agno.models.minimax.minimax.MiniMax": "MiniMax-M3",
    "agno.models.mistral.mistral.MistralChat": "mistral-large-latest",
    "agno.models.moonshot.moonshot.MoonShot": "kimi-k3",
    "agno.models.neosantara.neosantara.Neosantara": "grok-4.1-fast-non-reasoning",
    "agno.models.openai.like.OpenAILike": "not-provided",
    "agno.models.perplexity.perplexity.Perplexity": "sonar",
    "agno.models.siliconflow.siliconflow.Siliconflow": "Qwen/QwQ-32B",
    "agno.models.synthorai.synthorai.Synthorai": "claude-opus-5",
    "agno.models.together.together.Together": "MiniMaxAI/MiniMax-M2.7",
    "agno.models.trustedrouter.trustedrouter.TrustedRouter": "trustedrouter/zdr",
    "agno.models.vercel.v0.V0": "v0-1.0-md",
    "agno.models.vllm.vllm.VLLM": "not-set",
    "agno.models.xai.xai.xAI": "grok-4-1-fast-non-reasoning-latest",
    "agno.models.xiaomi.mimo.MiMo": "mimo-v2.5-pro",
}


def _iter_provider_classes() -> Tuple[List[Type[Model]], List[str]]:
    """All concrete provider classes under agno.models, plus import failures."""
    providers: List[Type[Model]] = []
    failures: List[str] = []
    for mod_info in pkgutil.walk_packages(agno.models.__path__, prefix="agno.models."):
        module_name = mod_info.name
        if ".tests" in module_name or module_name.endswith(".message"):
            continue
        try:
            module = importlib.import_module(module_name)
        except Exception as exc:
            failures.append(f"{module_name}: {type(exc).__name__}: {exc}")
            continue
        for attr_name in dir(module):
            try:
                obj = getattr(module, attr_name)
            except Exception:
                continue
            if (
                isinstance(obj, type)
                and issubclass(obj, Model)
                and obj is not Model
                and obj.__module__.startswith("agno.models.")
                and "Fallback" not in obj.__name__
                and all(obj is not seen for seen in providers)
            ):
                providers.append(obj)
    return providers, failures


def _default_model_id(cls: Type[Model]) -> Optional[str]:
    try:
        for f in fields(cls):
            if f.name == "id" and f.default is not MISSING:
                return f.default  # type: ignore[no-any-return]
    except Exception:
        pass
    return None


@requires_tokenizer_mapping
def test_every_provider_has_a_tokenizer_decision() -> None:
    providers, failures = _iter_provider_classes()
    assert not failures, "provider modules failed to import:\n" + "\n".join(failures)
    assert providers, "no provider classes found under agno.models"

    uncovered: List[str] = []
    for cls in providers:
        name = f"{cls.__module__}.{cls.__name__}"
        if cls.count_tokens is not Model.count_tokens:
            continue  # explicit override: conscious decision
        default_id = _default_model_id(cls)
        assert _is_family_mapped is not None  # guaranteed by requires_tokenizer_mapping
        if isinstance(default_id, str) and _is_family_mapped(default_id):
            continue  # covered by the family mapping
        if KNOWN_ESTIMATED_TOKENIZER_DEFAULTS.get(name, object()) == default_id:
            continue  # reviewed estimate, pinned at this default id
        uncovered.append(f"{name} (default id {default_id!r})")

    assert not uncovered, (
        "providers without a tokenizer decision (they would silently inherit "
        "o200k_base estimates):\n" + "\n".join(uncovered) + "\nMap the model family in "
        "HF_TOKENIZER_PATTERNS (agno/utils/tokens.py), override count_tokens on the "
        "provider, or pin the reviewed default id in KNOWN_ESTIMATED_TOKENIZER_DEFAULTS."
    )


@requires_tokenizer_mapping
def test_estimated_record_has_no_stale_entries() -> None:
    providers, _ = _iter_provider_classes()
    by_name = {f"{cls.__module__}.{cls.__name__}": cls for cls in providers}
    stale: List[str] = []
    for name, pinned_id in KNOWN_ESTIMATED_TOKENIZER_DEFAULTS.items():
        cls = by_name.get(name)
        if cls is None:
            stale.append(f"{name}: provider no longer exists")
            continue
        if cls.count_tokens is not Model.count_tokens:
            stale.append(f"{name}: now overrides count_tokens")
            continue
        default_id = _default_model_id(cls)
        if default_id != pinned_id:
            stale.append(f"{name}: default id changed {pinned_id!r} -> {default_id!r}")
            continue
        assert _is_family_mapped is not None  # guaranteed by requires_tokenizer_mapping
        if isinstance(default_id, str) and _is_family_mapped(default_id):
            stale.append(f"{name}: default id is now covered by the family mapping")
    assert not stale, "stale entries in KNOWN_ESTIMATED_TOKENIZER_DEFAULTS (remove them):\n" + "\n".join(stale)
