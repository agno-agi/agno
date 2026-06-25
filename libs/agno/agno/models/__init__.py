"""Lazy exports for Banavo-enhanced models (avoids import cycles with agno.models.message)."""

_BANAVO_MODEL_NAMES = frozenset({"Claude", "Model", "OpenAIChat", "OpenAIPromptCacheRetention", "OpenAIServiceTier"})


def __getattr__(name: str):
    if name in _BANAVO_MODEL_NAMES:
        from agno.banavo import models as banavo_models

        return getattr(banavo_models, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(list(_BANAVO_MODEL_NAMES))
