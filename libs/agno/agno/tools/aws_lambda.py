import json
from typing import Callable, List

from agno.tools import Toolkit

try:
    import boto3
except ImportError:
    raise ImportError("`boto3` not installed. Please install using `pip install boto3`")


class AWSLambdaTools(Toolkit):
    def __init__(
        self,
        region_name: str = "us-east-1",
        list_functions: bool = True,
        invoke_function: bool = True,
        all: bool = False,
        **kwargs,
    ):
        # Backwards compat: enable_X -> X
        if "enable_list_functions" in kwargs:
            list_functions = kwargs.pop("enable_list_functions")
        if "enable_invoke_function" in kwargs:
            invoke_function = kwargs.pop("enable_invoke_function")

        self.client = boto3.client("lambda", region_name=region_name)

        tools: List[Callable] = []
        if all or list_functions:
            tools.append(self.list_functions)
        if all or invoke_function:
            tools.append(self.invoke_function)

        super().__init__(name="aws_lambda_tools", tools=tools, **kwargs)

    def list_functions(self) -> str:
        """List all AWS Lambda functions in the configured account.

        Returns:
            JSON with list of function names.
        """
        try:
            response = self.client.list_functions()
            functions = [func["FunctionName"] for func in response["Functions"]]
            return json.dumps({"functions": functions})
        except Exception as e:
            return json.dumps({"error": f"Failed to list functions: {e}"})

    def invoke_function(self, function_name: str, payload: str = "{}") -> str:
        """Invoke an AWS Lambda function with an optional JSON payload.

        Args:
            function_name: The name of the Lambda function to invoke.
            payload: JSON payload to send to the function. Defaults to "{}".

        Returns:
            JSON with status_code and response payload.
        """
        try:
            response = self.client.invoke(FunctionName=function_name, Payload=payload)
            result_payload = response["Payload"].read().decode("utf-8")
            return json.dumps(
                {
                    "status_code": response["StatusCode"],
                    "payload": json.loads(result_payload) if result_payload else None,
                }
            )
        except Exception as e:
            return json.dumps({"error": f"Failed to invoke function: {e}"})
