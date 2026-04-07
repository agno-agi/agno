try:
    from agno.models.kelly_intelligence.kelly_intelligence import KellyIntelligence
except ImportError:

    class KellyIntelligence:  # type: ignore
        def __init__(self, *args, **kwargs):
            raise ImportError("`openai` not installed. Please install it via `pip install openai`")


__all__ = ["KellyIntelligence"]
