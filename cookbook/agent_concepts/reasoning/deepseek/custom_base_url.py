import os

## or set api key in bash shell
os.environ["ALIYUN_API_KEY"] = "sk-**"

## use Aliyun api for example, should comply with the OpenAI interface specification
base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"

task = "How many 'r' are in the word 'strawberry'?"

reasoning_agent = Agent(
    model=DeepSeek(
        id="deepseek-v3", 
        base_url=base_url,
        api_key=os.getenv("ALIYUN_API_KEY")),
    reasoning_model=DeepSeek(
        id="deepseek-r1", 
        base_url=base_url,
        api_key=os.getenv("ALIYUN_API_KEY")),
    markdown=True,
)
reasoning_agent.print_response(task, stream=True)
