from agno.agent import Agent
from agno.media import Image
from agno.models.dashscope import DashScope

agent = Agent(
    model=DashScope(id="qvq-max", enable_thinking=True),
)

image_url = "https://img.alicdn.com/imgextra/i1/O1CN01gDEY8M1W114Hi3XcN_!!6000000002727-0-tps-1024-406.jpg"

agent.print_response(
    "How do I solve this problem? Please think through each step carefully.",
    images=[Image(url=image_url)],
    stream=True,
)
