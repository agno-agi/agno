from pydantic import BaseModel, Field

CHAT_VALIDATION_PROMPT = f"""
Based on the following results, determine if the user's query is relevant to the provided results. 

<Rules>
- Make sure to only return True if the user's query is relevant to the provided results and users query can be answered based on the provided results.
- Make sure to only return False if the user's query is not relevant to the provided results or users query cannot be answered based on the provided results.
- Make sure to provide a reason for your answer.
</Rules>
"""

CHAT_PROMPT = f"""
Based on the following results, answer the user's query. 

<Rules>
- Make sure to reply to users query using the provided results as your knowledge.
- Be detailed and provide a comprehensive answer.
</Rules>
"""


def get_chat_validation_prompt(input_message: str, previous_results: str) -> str:
    return f"""
    Based on the following results, determine if the user's query is relevant to the provided results. 
    Make sure to 
    If the user's query is relevant to the provided results, you will return True.
    If the user's query is not relevant to the provided results, you will return False.
    User query: {input_message}
    Previous results: {previous_results}
    """


def get_chat_prompt(input_message: str, previous_results: str) -> str:
    return f"""
    Based on the following results, answer the user's query.
    User query: {input_message}
    Previous results: {previous_results}
    """


class ChatStepValidation(BaseModel):
    relevant: bool = Field(description="Whether the user's query can be answered based on the provided results")
    reason: str = Field(description="The reason for the answer")
