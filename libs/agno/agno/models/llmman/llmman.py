from dataclasses import dataclass

from agno.models.openai.like import OpenAILike


@dataclass
class Llmman(OpenAILike):
    """
    A class for interacting with llmman (https://github.com/llmmanorg/llmman).

    Attributes:
        id (str): The id of the llmman model. Default is "qwen3:0.6b-q4_K_M".
        name (str): The name of this chat model instance. Default is "Llmman".
        provider (str): The provider of the model. Default is "Llmman".
        base_url (str): The base url to which the requests are sent.
    """

    id: str = "qwen3:0.6b-q4_K_M"
    name: str = "Llmman"
    provider: str = "Llmman"

    base_url: str = "http://127.0.0.1:17434/v1"

    # llmman has no native structured outputs, but does accept a json_schema.
    supports_native_structured_outputs: bool = False
    supports_json_schema_outputs: bool = True
