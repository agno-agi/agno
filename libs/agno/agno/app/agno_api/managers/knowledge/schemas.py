from pydantic import BaseModel


class DocumentSchema(BaseModel):
    name: str
    content: str
    # TODO: add other fields
