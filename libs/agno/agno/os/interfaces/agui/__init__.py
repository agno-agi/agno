import warnings

from agno.os.interfaces.agui.agui import AGUI

# Suppress Pydantic v2 UnsupportedFieldAttributeWarning from ag_ui models.
# The ag_ui library uses alias_generator=to_camel in ConfigDict, which in some
# Pydantic v2 versions triggers spurious warnings about field aliases having no
# effect when models are used in discriminated unions or FastAPI route parameters.
warnings.filterwarnings(
    "ignore",
    message=r".*alias.*",
    category=UserWarning,
    module=r"pydantic\._internal\._generate_schema",
)

__all__ = ["AGUI"]
