import re
from textwrap import dedent
from typing import Any, Callable, Dict, List, Optional, Type, Union, cast

from pydantic import BaseModel

from agno.knowledge.document.base import Document
from agno.models.base import Model
from agno.models.defaults import DEFAULT_OPENAI_MODEL_ID
from agno.models.message import Message
from agno.models.utils import get_model
from agno.utils.prompts import get_json_output_prompt
from agno.utils.string import parse_response_dict_str, parse_response_model_str

ChunkMetadataExtractor = Callable[[Document, str, int], Dict[str, Any]]
ChunkMetadataOutputSchema = Union[str, List[str], Dict[str, Any], Type[BaseModel]]


_TEMPLATE_PATTERN = re.compile(r"\{(chunk_number|chunk_size|document_id|document_name|text)\}")


class LLMChunkMetadataExtractor:
    """Extract metadata for chunks using an LLM.

    This is intentionally lightweight and pluggable: pass an instance as `metadata_extractor` to `AgenticChunking`.

    Args:
        model: Model instance or model string (e.g., "openai:gpt-4o-mini"). Defaults to OpenAIChat if available.
        prompt_template: Optional prompt template for extraction. Supports placeholders:
            - {text}: The chunk text
            - {chunk_number}: The 1-based chunk index
            - {chunk_size}: Number of characters in the chunk text
            - {document_name}: `Document.name` (if available)
            - {document_id}: `Document.id` (if available)
        output_schema: Optional schema/field spec for structured outputs. If provided, this is used to guide the model
            and parse responses. Supported: Pydantic BaseModel type, dict, list, or str.
    """

    def __init__(
        self,
        model: Optional[Union[Model, str]] = None,
        prompt_template: Optional[str] = None,
        output_schema: Optional[ChunkMetadataOutputSchema] = None,
    ):
        model = get_model(model)
        if model is None:
            try:
                from agno.models.openai import OpenAIChat
            except Exception:
                raise ValueError("`openai` isn't installed. Please install it with `pip install openai`")
            model = OpenAIChat(DEFAULT_OPENAI_MODEL_ID)

        self.model: Model = model
        self.prompt_template = prompt_template
        self.output_schema = output_schema

    def __call__(self, document: Document, chunk_text: str, chunk_number: int) -> Dict[str, Any]:
        prompt = self._build_prompt(document=document, chunk_text=chunk_text, chunk_number=chunk_number)
        response_format = self._get_response_format()

        response = self.model.response(messages=[Message(role="user", content=prompt)], response_format=response_format)
        return self._parse_response(response=response)

    def _build_prompt(self, *, document: Document, chunk_text: str, chunk_number: int) -> str:
        base_prompt = self.prompt_template or dedent(
            """\
            Extract metadata for the following text chunk.

            <chunk>
            {text}
            </chunk>
            """
        )

        rendered_prompt = self._render_template(
            base_prompt,
            document=document,
            chunk_text=chunk_text,
            chunk_number=chunk_number,
        ).strip()

        schema_prompt = get_json_output_prompt(self.output_schema)  # type: ignore[arg-type]
        return f"{rendered_prompt}\n\n{schema_prompt}".strip()

    def _render_template(self, template: str, *, document: Document, chunk_text: str, chunk_number: int) -> str:
        document_name = document.name or ""
        document_id = document.id or ""

        replacements = {
            "chunk_number": str(chunk_number),
            "chunk_size": str(len(chunk_text)),
            "document_name": document_name,
            "document_id": document_id,
            "text": chunk_text,
        }

        def _replace(match: re.Match[str]) -> str:
            key = match.group(1)
            return replacements.get(key, match.group(0))

        return _TEMPLATE_PATTERN.sub(_replace, template)

    def _get_response_format(self) -> Union[Dict[str, Any], Type[BaseModel]]:
        if isinstance(self.output_schema, type) and issubclass(self.output_schema, BaseModel):
            if self.model.supports_native_structured_outputs:
                return self.output_schema
            if self.model.supports_json_schema_outputs:
                schema = self.output_schema.model_json_schema()
                return {"type": "json_schema", "json_schema": {"name": self.output_schema.__name__, "schema": schema}}

        return {"type": "json_object"}

    def _parse_response(self, *, response: Any) -> Dict[str, Any]:
        if response is None:
            return {}

        # Prefer provider-native parsing if available.
        parsed_obj = getattr(response, "parsed", None)
        if isinstance(parsed_obj, BaseModel):
            return cast(Dict[str, Any], parsed_obj.model_dump(mode="json"))
        if isinstance(parsed_obj, dict):
            return parsed_obj

        content = getattr(response, "content", None)
        if isinstance(content, dict):
            return content

        if isinstance(content, str) and content.strip():
            if isinstance(self.output_schema, type) and issubclass(self.output_schema, BaseModel):
                parsed_model = parse_response_model_str(content, self.output_schema)
                if isinstance(parsed_model, BaseModel):
                    return cast(Dict[str, Any], parsed_model.model_dump(mode="json"))

            parsed_dict = parse_response_dict_str(content)
            if isinstance(parsed_dict, dict):
                return parsed_dict

        return {}
