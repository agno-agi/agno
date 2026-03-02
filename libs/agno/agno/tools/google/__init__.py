__all__ = [
    "GoogleSlidesTools",
]


def __getattr__(name: str):
    if name == "GoogleSlidesTools":
        from agno.tools.google.slides import GoogleSlidesTools

        return GoogleSlidesTools
    raise AttributeError(f"module 'agno.tools.google' has no attribute {name!r}")
