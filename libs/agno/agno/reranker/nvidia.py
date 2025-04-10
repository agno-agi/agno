from typing import List, Optional


from agno.document import Document
from agno.reranker.base import Reranker
from agno.utils.log import logger

try:
    from langchain_nvidia_ai_endpoints import NVIDIARerank
except ImportError:
    raise ImportError(
        "langchain_nvidia_ai_endpoints is not installed, please run pip install langchain-nvidia-ai-endpoint"
    )

try:
    from langchain.docstore.document import Document as LCDocument
except ImportError:
    raise ImportError(
        "langchain is not installed, please run pip install langchain"
    )

class NVIDIALangchainReranker(Reranker):
    model: str = "nvidia/llama-3.2-nv-rerankqa-1b-v2"
    api_key: Optional[str] = None
    top_n: Optional[int] = None

    def _rerank(self, query: str, documents: List[Document]) -> List[Document]:
        # Validate input documents and top_n
        if not documents:
            return []

        top_n = self.top_n
        if top_n and not (0 < top_n):
            logger.warning(f"top_n should be a positive integer, got {self.top_n}, setting top_n to None")
            top_n = None

        # Create a list of Documents in the langchain format
        lc_docs: list[LCDocuments] = []
        for doc in documents:
            lc_docs.append(
                LCDocument(
                    page_content=doc.content,
                )
            )

        # Rerank using the NVIDIARerank from langchain
        reranker = NVIDIARerank(model=self.model)
        response = reranker.compress_documents(query=query, documents=lc_docs)

        # convert back to Agno's Document format
        compressed_docs: list[Document] = []
        for r in response:
            compressed_docs.append(Document(content=r.page_content, reranking_score=r.metadata["relevance_score"]))

        # Order by relevance score
        compressed_docs.sort(
            key=lambda x: x.reranking_score if x.reranking_score is not None else float("-inf"),
            reverse=True,
        )

        # Limit to top_n if specified
        if top_n:
            compressed_docs = compressed_docs[:top_n]

        return compressed_docs

    def rerank(self, query: str, documents: List[Document]) -> List[Document]:
        try:
            return self._rerank(query=query, documents=documents)
        except Exception as e:
            logger.error(f"Error reranking documents: {e}. Returning original documents")
            return documents
