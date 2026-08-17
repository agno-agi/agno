import os

import pytest

from agno.knowledge.embedder.siliconflow import SiliconflowEmbedder

pytestmark = pytest.mark.skipif(not os.getenv("SILICONFLOW_API_KEY"), reason="SILICONFLOW_API_KEY not set")


def test_siliconflow_embedder_live_batch():
    embedder = SiliconflowEmbedder()

    embeddings, usages = embedder.get_embeddings_batch_and_usage(
        ["The Eiffel Tower is in Paris.", "Python is a programming language."]
    )

    assert len(embeddings) == len(usages) == 2
    assert all(len(embedding) == 1024 for embedding in embeddings)
    assert all(isinstance(value, float) for embedding in embeddings for value in embedding)
