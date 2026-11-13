"""Record document and query embedding requests without credentials or network calls."""

import asyncio
from types import SimpleNamespace

from agno.knowledge.document import Document
from agno.knowledge.embedder.google import GeminiEmbedder


def record_embedding_request(**kwargs):
    contents = kwargs["contents"]
    print(kwargs["config"]["task_type"], contents)
    texts = contents if isinstance(contents, list) else [contents]
    return SimpleNamespace(
        embeddings=[SimpleNamespace(values=[1.0, 0.0]) for _ in texts], metadata=None
    )


async def record_async_embedding_request(**kwargs):
    return record_embedding_request(**kwargs)


async def main():
    # The recorder stands in for the SDK client; the embedder builds real request parameters.
    client = SimpleNamespace(
        models=SimpleNamespace(embed_content=record_embedding_request),
        aio=SimpleNamespace(
            models=SimpleNamespace(embed_content=record_async_embedding_request)
        ),
    )
    embedder = GeminiEmbedder(dimensions=2, gemini_client=client)
    document = Document(content="The archive opens at nine.")

    # Document ingestion supplies purpose="document" automatically.
    document.embed(embedder)
    embedder.get_embedding("When does the archive open?", purpose="query")

    await document.async_embed(embedder)
    await embedder.async_get_embeddings_batch_and_usage(
        [document.content, "The archive closes at five."], purpose="document"
    )
    await embedder.async_get_embedding("When does the archive close?", purpose="query")


if __name__ == "__main__":
    asyncio.run(main())
