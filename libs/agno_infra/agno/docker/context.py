from pydantic import BaseModel


class DockerBuildContext(BaseModel):
    network: str
