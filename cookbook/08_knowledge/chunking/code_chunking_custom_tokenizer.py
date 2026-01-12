from typing import Sequence

from agno.agent import Agent
from agno.knowledge.chunking.code import CodeChunking
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.text_reader import TextReader
from agno.vectordb.pgvector import PgVector
from chonkie.tokenizer import Tokenizer

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"


class LineTokenizer(Tokenizer):
    """Custom tokenizer that counts lines of code."""

    def __repr__(self) -> str:
        return f"LineTokenizer(vocab_size={len(self.vocab)})"

    def tokenize(self, text: str) -> Sequence[str]:
        if not text:
            return []
        return text.split("\n")

    def encode(self, text: str) -> Sequence[int]:
        encoded = []
        for token in self.tokenize(text):
            id = self.token2id[token]
            if id >= len(self.vocab):
                self.vocab.append(token)
            encoded.append(id)
        return encoded

    def decode(self, tokens: Sequence[int]) -> str:
        try:
            return "\n".join([self.vocab[token] for token in tokens])
        except Exception as e:
            raise ValueError(
                f"Decoding failed. Tokens: {tokens} not found in vocab."
            ) from e

    def count_tokens(self, text: str) -> int:
        if not text:
            return 0
        return len(text.split("\n"))


knowledge = Knowledge(
    vector_db=PgVector(table_name="code_custom_tokenizer", db_url=db_url),
)

knowledge.add_content(
    url="https://raw.githubusercontent.com/agno-agi/agno/main/libs/agno/agno/session/workflow.py",
    reader=TextReader(
        chunking_strategy=CodeChunking(
            tokenizer=LineTokenizer(),
            chunk_size=500,
            language="python",
        ),
    ),
)

agent = Agent(
    knowledge=knowledge,
    search_knowledge=True,
)

agent.print_response("How does the Workflow class work?", markdown=True)
