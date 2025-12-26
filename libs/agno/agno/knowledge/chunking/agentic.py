import json
import re
from textwrap import dedent
from typing import Any, Dict, List, Optional, Set, Union

from agno.knowledge.chunking.metadata import ChunkMetadataExtractor
from agno.knowledge.chunking.strategy import ChunkingStrategy
from agno.knowledge.document.base import Document
from agno.models.base import Model
from agno.models.defaults import DEFAULT_OPENAI_MODEL_ID
from agno.models.message import Message
from agno.models.utils import get_model
from agno.utils.log import log_warning
from agno.utils.string import parse_response_dict_str

_DEFAULT_BREAKPOINT_PROMPT_TEMPLATE = dedent(
    """\
    Analyze this text and determine a natural breakpoint within the first {chunk_size} characters.
    Consider semantic completeness, paragraph boundaries, and topic transitions.
    Return only the character position number of where to break the text:

    {text}
    """
).strip()

_TEMPLATE_PATTERN = re.compile(r"\{(chunk_number|chunk_size|document_id|document_name|text)\}")
_INT_PATTERN = re.compile(r"-?\d+")
_RESERVED_META_KEYS: Set[str] = {"chunk", "chunk_size"}


class AgenticChunking(ChunkingStrategy):
    """Chunking strategy that uses an LLM to determine natural breakpoints in the text"""

    def __init__(
        self,
        model: Optional[Union[Model, str]] = None,
        max_chunk_size: int = 5000,
        breakpoint_prompt_template: Optional[str] = None,
        metadata_extractor: Optional[ChunkMetadataExtractor] = None,
    ):
        # Convert model string to Model instance
        model = get_model(model)
        if model is None:
            try:
                from agno.models.openai import OpenAIChat
            except Exception:
                raise ValueError("`openai` isn't installed. Please install it with `pip install openai`")
            model = OpenAIChat(DEFAULT_OPENAI_MODEL_ID)
        self.chunk_size = max_chunk_size
        self.model = model
        self.breakpoint_prompt_template = breakpoint_prompt_template
        self.metadata_extractor = metadata_extractor

    def chunk(self, document: Document) -> List[Document]:
        """Split text into chunks using LLM to determine natural breakpoints based on context"""
        if len(document.content) <= self.chunk_size:
            return [document]

        chunks: List[Document] = []
        remaining_text = self.clean_text(document.content)
        chunk_meta_data = document.meta_data
        chunk_number = 1

        while remaining_text:
            window_text = remaining_text[: self.chunk_size]
            prompt_template = self.breakpoint_prompt_template or _DEFAULT_BREAKPOINT_PROMPT_TEMPLATE
            prompt = self._render_breakpoint_prompt(
                prompt_template,
                document=document,
                chunk_number=chunk_number,
                window_text=window_text,
            )

            response_content: Optional[Any] = None
            try:
                response = self.model.response([Message(role="user", content=prompt)])
                response_content = response.content if response is not None else None
            except Exception:
                response_content = None

            break_point = self._parse_breakpoint(response_content=response_content, max_break_point=len(window_text))

            # Extract chunk and update remaining text
            chunk = remaining_text[:break_point].strip()
            meta_data = chunk_meta_data.copy()
            meta_data["chunk"] = chunk_number
            chunk_id = None
            if document.id:
                chunk_id = f"{document.id}_{chunk_number}"
            elif document.name:
                chunk_id = f"{document.name}_{chunk_number}"
            meta_data["chunk_size"] = len(chunk)

            self._enrich_chunk_metadata(meta_data, document=document, chunk_text=chunk, chunk_number=chunk_number)
            chunks.append(
                Document(
                    id=chunk_id,
                    name=document.name,
                    meta_data=meta_data,
                    content=chunk,
                )
            )
            chunk_number += 1

            remaining_text = remaining_text[break_point:].strip()

            if not remaining_text:
                break

        return chunks

    def _render_breakpoint_prompt(
        self,
        template: str,
        *,
        document: Document,
        chunk_number: int,
        window_text: str,
    ) -> str:
        document_name = document.name or ""
        document_id = document.id or ""

        replacements = {
            "chunk_number": str(chunk_number),
            "chunk_size": str(self.chunk_size),
            "document_name": document_name,
            "document_id": document_id,
            "text": window_text,
        }

        def _replace(match: re.Match[str]) -> str:
            key = match.group(1)
            return replacements.get(key, match.group(0))

        return _TEMPLATE_PATTERN.sub(_replace, template).strip()

    def _parse_breakpoint(self, *, response_content: Any, max_break_point: int) -> int:
        if max_break_point <= 0:
            return 0

        break_point: Optional[int] = None

        if isinstance(response_content, int):
            break_point = response_content
        elif isinstance(response_content, str):
            content = response_content.strip()
            if content:
                try:
                    break_point = int(content)
                except Exception:
                    parsed_dict = parse_response_dict_str(content)
                    if isinstance(parsed_dict, dict):
                        for key in ("break_point", "breakpoint", "position", "index"):
                            if key in parsed_dict:
                                try:
                                    break_point = int(str(parsed_dict[key]).strip())
                                except Exception:
                                    break_point = None
                                break

                    if break_point is None:
                        match = _INT_PATTERN.search(content)
                        if match:
                            try:
                                break_point = int(match.group(0))
                            except Exception:
                                break_point = None

        if break_point is None:
            break_point = max_break_point

        # Clamp into safe bounds to ensure progress and avoid empty chunks.
        if break_point < 1:
            break_point = 1
        if break_point > max_break_point:
            break_point = max_break_point

        return break_point

    def _enrich_chunk_metadata(
        self,
        meta_data: Dict[str, Any],
        *,
        document: Document,
        chunk_text: str,
        chunk_number: int,
    ) -> None:
        if self.metadata_extractor is None:
            return

        try:
            extracted = self.metadata_extractor(document, chunk_text, chunk_number)
        except Exception as e:
            log_warning(f"Chunk metadata extraction failed: {e}")
            return

        if not isinstance(extracted, dict) or not extracted:
            return

        for key, value in extracted.items():
            if not isinstance(key, str):
                continue
            if key in _RESERVED_META_KEYS:
                continue
            if key in meta_data:
                continue
            if value is None:
                continue
            if not self._is_json_serializable(value):
                log_warning(f"Skipping non-JSON-serializable chunk metadata field '{key}'")
                continue
            meta_data[key] = value

    def _is_json_serializable(self, value: Any) -> bool:
        try:
            json.dumps(value)
        except (TypeError, ValueError):
            return False
        return True
