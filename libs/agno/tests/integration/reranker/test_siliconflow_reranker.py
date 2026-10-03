import os

import pytest

from agno.knowledge.document import Document
from agno.knowledge.reranker.siliconflow import SiliconflowReranker

pytestmark = pytest.mark.skipif(not os.getenv("SILICONFLOW_API_KEY"), reason="SILICONFLOW_API_KEY not set")


def test_siliconflow_reranker_live():
    documents = [
        Document(content="The Eiffel Tower is in Paris."),
        Document(content="Python is a programming language."),
        Document(content="Paris is the capital of France."),
    ]
    reranker = SiliconflowReranker(top_n=2, raise_on_error=True)

    result = reranker.rerank("Where is the Eiffel Tower?", documents)

    assert len(result) == 2
    assert all(document in documents for document in result)
    assert all(document.reranking_score is not None for document in result)
    assert result[0].reranking_score >= result[1].reranking_score
