"""This cookbook is an implementation of Agentic RAG using Sentence Transformer Reranker with multilingual data.

## Setup Instructions:

### 1. Install Dependencies
Run: `pip install agno sentence-transformers`

### 2. Start the Postgres Server with pgvector
Run: `sh cookbook/scripts/run_pgvector.sh`

### 3. Run the example
Run: `uv run cookbook/agent_concepts/rag/rag_sentence_transformer.py`
"""

from agno.agent import Agent
from agno.knowledge.embedder.sentence_transformer import SentenceTransformerEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reranker.sentence_transformer import SentenceTransformerReranker
from agno.models.openai import OpenAIChat
from agno.vectordb.pgvector import PgVector

search_results = [
    "Organic skincare for sensitive skin with aloe vera and chamomile.",
    "New makeup trends focus on bold colors and innovative techniques",
    "Bio-Hautpflege für empfindliche Haut mit Aloe Vera und Kamille",
    "Neue Make-up-Trends setzen auf kräftige Farben und innovative Techniken",
    "Cuidado de la piel orgánico para piel sensible con aloe vera y manzanilla",
    "Las nuevas tendencias de maquillaje se centran en colores vivos y técnicas innovadoras",
    "针对敏感肌专门设计的天然有机护肤产品",
    "新的化妆趋势注重鲜艳的颜色和创新的技巧",
    "敏感肌のために特別に設計された天然有機スキンケア製品",
    "新しいメイクのトレンドは鮮やかな色と革新的な技術に焦点を当てています",
]

knowledge = Knowledge(
    vector_db=PgVector(
        db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
        table_name="sentence_transformer_rerank_docs",
        embedder=SentenceTransformerEmbedder(
            id="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
        ),
        reranker=SentenceTransformerReranker(model="BAAI/bge-reranker-v2-m3"),
    ),
)

for result in search_results:
    knowledge.add_content(
        text_content=result,
        metadata={
            "source": "search_results",
        },
    )

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    knowledge=knowledge,
    search_knowledge=True,
    instructions=[
        "Include sources in your response.",
        "Always search your knowledge before answering the question.",
    ],
    markdown=True,
)

if __name__ == "__main__":
    test_queries = [
        "What organic skincare products are good for sensitive skin?",
        "Tell me about makeup trends in different languages",
        "Compare skincare and makeup information across languages",
    ]

    for query in test_queries:
        agent.print_response(
            query,
            stream=True,
            show_full_reasoning=True,
        )
