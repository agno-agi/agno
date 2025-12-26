from textwrap import dedent

from agno.knowledge.chunking.agentic import AgenticChunking
from agno.knowledge.chunking.metadata import LLMChunkMetadataExtractor
from agno.knowledge.document.base import Document
from pydantic import BaseModel, Field


class ChunkMeta(BaseModel):
    chunk_type: str = Field(
        description="High-level section label for this chunk, e.g. 'general_info', 'abstract', 'methods', 'references'."
    )


breakpoint_prompt_template = dedent(
    """\
    You are chunking a scientific paper. Choose a breakpoint within the first {chunk_size} characters.
    Prefer splitting at section boundaries such as 'Abstract', 'Introduction', 'Methods', 'Results', 'Discussion', 'References'.

    Return ONLY the integer character position (no words, no JSON).

    <text>
    {text}
    </text>
    """
).strip()

metadata_prompt_template = dedent(
    """\
    Identify the section type for this chunk and return it as JSON.
    Use one of: general_info, abstract, introduction, methods, results, discussion, references, other.

    <chunk>
    {text}
    </chunk>
    """
).strip()


chunker = AgenticChunking(
    max_chunk_size=800,
    breakpoint_prompt_template=breakpoint_prompt_template,
    metadata_extractor=LLMChunkMetadataExtractor(
        prompt_template=metadata_prompt_template,
        output_schema=ChunkMeta,
    ),
)

paper_text = dedent(
    """\
    RESEARCH Open Access
    Automatic extraction of informal topics from online suicidal ideation
    Reilly N. Grant1, David Kucher2, Ana M. León3, Jonathan F. Gemmell4*, Daniela S. Raicu4 and Samah J. Fodeh5

    From The 11th International Workshop on Data and Text Mining in Biomedical Informatics Singapore, Singapore. 10 November 2017

    Abstract

    Background: Suicide is an alarming public health problem accounting for a considerable number of deaths each year worldwide.
    Methods: We propose a method to automatically extract informal topics from online suicidal ideation posts.
    Results: The extracted topics improve interpretability while maintaining strong performance.
    Conclusions: Informal topics provide actionable insights for downstream analysis.
    Keywords: Suicidal ideation, Word2Vec, Text mining
    """
).strip()

doc = Document(name="paper_example", content=paper_text)
chunks = chunker.chunk(doc)

for chunk in chunks:
    chunk_type = chunk.meta_data.get("chunk_type", "unknown")
    print(f"Chunk {chunk.meta_data['chunk']} ({chunk_type})")
    print(chunk.content)
    print("---")
