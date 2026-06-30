from pydantic import BaseModel


class ApiResponseSchema(BaseModel):
    status: str = "fail"
    message: str = "invalid request"
