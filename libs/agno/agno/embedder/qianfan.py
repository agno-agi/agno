from agno.embedder.openai import OpenAIEmbedder


class QianfanEmbedder(OpenAIEmbedder):
    id: str = "tao-8k"
    base_url = "https://qianfan.baidubce.com/v2"
    dimensions = 1024

    def __post_init__(self):
        if self.dimensions is None:
            self.dimensions = 1024 if self.id == "tao-8k" else 1536
