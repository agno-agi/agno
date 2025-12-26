from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional, Type, Union

from pydantic import BaseModel

from agno.knowledge.chunking.agentic import AgenticChunking
from agno.knowledge.chunking.metadata import LLMChunkMetadataExtractor
from agno.knowledge.document.base import Document
from agno.models.base import Model
from agno.models.message import Message
from agno.models.response import ModelResponse


@dataclass
class DummyModel(Model):
    responses: List[Any] = field(default_factory=list)
    prompts: List[str] = field(default_factory=list)
    default_response: str = "9999"

    def invoke(
        self,
        messages: List[Message],
        assistant_message: Message,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        run_response: Any = None,
        compress_tool_results: bool = False,
    ) -> ModelResponse:
        if messages:
            last = messages[-1]
            self.prompts.append(last.content if isinstance(last.content, str) else str(last.content))

        content = self.responses.pop(0) if self.responses else self.default_response
        return ModelResponse(role="assistant", content=content)

    async def ainvoke(self, *args, **kwargs) -> ModelResponse:  # type: ignore[override]
        return self.invoke(*args, **kwargs)

    def invoke_stream(self, *args, **kwargs) -> Iterator[ModelResponse]:  # type: ignore[override]
        raise NotImplementedError

    async def ainvoke_stream(self, *args, **kwargs) -> AsyncIterator[ModelResponse]:  # type: ignore[override]
        raise NotImplementedError

    def _parse_provider_response(self, response: Any, **kwargs) -> ModelResponse:  # type: ignore[override]
        raise NotImplementedError

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:  # type: ignore[override]
        raise NotImplementedError


def test_agentic_chunking_uses_custom_breakpoint_prompt_template():
    model = DummyModel(id="dummy", responses=["5"])
    chunking = AgenticChunking(
        model=model,
        max_chunk_size=5,
        breakpoint_prompt_template="BREAKPOINT within {chunk_size}:\n{text}",
    )

    doc = Document(content="abcdefghij", name="MyDoc")
    chunks = chunking.chunk(doc)

    assert len(chunks) >= 2
    assert model.prompts
    assert "BREAKPOINT within 5" in model.prompts[0]
    assert "abcde" in model.prompts[0]


def test_agentic_chunking_parses_breakpoint_from_json_response():
    model = DummyModel(id="dummy", responses=['{"break_point": 3}'])
    chunking = AgenticChunking(model=model, max_chunk_size=5)

    doc = Document(content="abcdefghij", name="MyDoc")
    chunks = chunking.chunk(doc)

    assert chunks[0].content == "abc"
    assert chunks[0].meta_data["chunk_size"] == 3


def test_agentic_chunking_clamps_breakpoint_to_safe_range():
    model = DummyModel(id="dummy", responses=["0"])
    chunking = AgenticChunking(model=model, max_chunk_size=5)

    doc = Document(content="abcdef", name="MyDoc")
    chunks = chunking.chunk(doc)

    assert chunks[0].content == "a"
    assert chunks[0].meta_data["chunk_size"] == 1


def test_agentic_chunking_enriches_metadata_without_overwriting_reserved_fields():
    def extractor(_document: Document, _chunk_text: str, _chunk_number: int) -> Dict[str, Any]:
        return {"chunk": 999, "chunk_size": 999, "chunk_type": "abstract", "page": 2}

    model = DummyModel(id="dummy", responses=["5"])
    chunking = AgenticChunking(model=model, max_chunk_size=5, metadata_extractor=extractor)

    doc = Document(content="abcdefghij", name="MyDoc", meta_data={"page": 1})
    chunks = chunking.chunk(doc)

    assert chunks
    assert chunks[0].meta_data["chunk"] == 1
    assert chunks[0].meta_data["chunk_size"] == len(chunks[0].content)
    assert chunks[0].meta_data["chunk_type"] == "abstract"
    assert chunks[0].meta_data["page"] == 1


def test_agentic_chunking_metadata_extractor_failure_does_not_break_chunking():
    def failing_extractor(_document: Document, _chunk_text: str, _chunk_number: int) -> Dict[str, Any]:
        raise RuntimeError("boom")

    model = DummyModel(id="dummy", responses=["5"])
    chunking = AgenticChunking(model=model, max_chunk_size=5, metadata_extractor=failing_extractor)

    doc = Document(content="abcdefghij", name="MyDoc")
    chunks = chunking.chunk(doc)

    assert len(chunks) >= 2
    assert all("chunk_type" not in c.meta_data for c in chunks)


def test_llm_chunk_metadata_extractor_parses_pydantic_schema():
    class ChunkMeta(BaseModel):
        chunk_type: str

    model = DummyModel(id="dummy", responses=['{"chunk_type": "Abstract"}'])
    extractor = LLMChunkMetadataExtractor(model=model, output_schema=ChunkMeta)

    doc = Document(content="ignored", name="MyDoc")
    meta = extractor(doc, "Abstract\n\nBackground: ...", 1)

    assert meta == {"chunk_type": "Abstract"}
