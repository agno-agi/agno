from pydantic import BaseModel

class KnowledgeRow(BaseModel):
    id: str
    name: str
    description: str
    content: str
    metadata: dict