from agno.tools import Toolkit

try:
    import boto3
except ImportError:
    raise ImportError("boto3 is required for AWSLambdaTool. Please install it using `pip install boto3`.")


class AWSLambdaTools(Toolkit):
    name: str = "AWSLambdaTool"
    description: str = "A tool for interacting with AWS Lambda functions"

    def __init__(self, region_name: str = "us-east-1", **kwargs):
        super().__init__(name="aws-lambda", **kwargs)
        self.client = boto3.client("lambda", region_name=region_name)
        self.register(self.list_functions)
        self.register(self.invoke_function)

    def list_functions(self) -> str:
        try:
            response = self.client.list_functions()
            functions = [func["FunctionName"] for func in response["Functions"]]
            return f"Available Lambda functions: {', '.join(functions)}"
        except Exception as e:
            return f"Error listing functions: {str(e)}"

    def invoke_function(self, function_name: str, payload: str = "{}") -> str:
        try:
            response = self.client.invoke(FunctionName=function_name, Payload=payload)
            return f"Function invoked successfully. Status code: {response['StatusCode']}, Payload: {response['Payload'].read().decode('utf-8')}"
        except Exception as e:
            return f"Error invoking function: {str(e)}"
