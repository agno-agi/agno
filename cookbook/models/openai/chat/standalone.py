"""
This example shows how to use the OpenAIChat model as a standalone model.
"""

from agno.agent import Message
from agno.models.openai import OpenAIChat
from agno.models.response import ModelResponse

model = OpenAIChat(id="gpt-4o")

response: ModelResponse = model.invoke(messages=[Message(role="user", content="Hello, how are you?")])

print(response.content)