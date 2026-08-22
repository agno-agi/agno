from typing import Any, List

from agno.tools import Toolkit

try:
    import boto3
except ImportError:
    raise ImportError("boto3 is required for AWSLambdaTool. Please install it using `pip install boto3`.")


class AWSLambdaTools(Toolkit):
    def __init__(
        self,
        region_name: str = "us-east-1",
        enable_list_functions: bool = True,
        enable_invoke_function: bool = True,
        get_function_config: bool = True,
        get_function_concurrency: bool = True,
        get_function_url: bool = True,
        all: bool = False,
        **kwargs,
    ):
        self.client = boto3.client("lambda", region_name=region_name)

        tools: List[Any] = []
        if all or enable_list_functions:
            tools.append(self.list_functions)
        if all or enable_invoke_function:
            tools.append(self.invoke_function)
        if all or get_function_config:
            tools.append(self.get_function_config)
        if all or get_function_concurrency:
            tools.append(self.get_function_concurrency)
        if all or get_function_url:
            tools.append(self.get_function_url)

        super().__init__(name="aws-lambda", tools=tools, **kwargs)

    def list_functions(self) -> str:
        """
        List all AWS Lambda functions in the configured AWS account.
        """
        try:
            response = self.client.list_functions()
            functions = [func["FunctionName"] for func in response["Functions"]]
            return f"Available Lambda functions: {', '.join(functions)}"
        except Exception as e:
            return f"Error listing functions: {str(e)}"

    def invoke_function(self, function_name: str, payload: str = "{}") -> str:
        """
        Invoke a specific AWS Lambda function with an optional JSON payload.

        Args:
            function_name (str): The name of the Lambda function to invoke.
            payload (str): The JSON payload to send to the function. Defaults to "{}".
        """
        try:
            response = self.client.invoke(FunctionName=function_name, Payload=payload)
            return f"Function invoked successfully. Status code: {response['StatusCode']}, Payload: {response['Payload'].read().decode('utf-8')}"
        except Exception as e:
            return f"Error invoking function: {str(e)}"

    def get_function_config(self, function_name: str) -> str:
        """
        Get the configuration of a Lambda function including runtime, memory, timeout, etc.

        Args:
            function_name (str): The name or ARN of the Lambda function.
        """
        try:
            response = self.client.get_function_configuration(FunctionName=function_name)
            config_info = {
                "Runtime": response.get("Runtime"),
                "Memory": f"{response.get('MemorySize')} MB",
                "Timeout": f"{response.get('Timeout')} seconds",
                "Handler": response.get("Handler"),
                "LastModified": response.get("LastModified"),
                "CodeSize": f"{response.get('CodeSize')} bytes",
                "Description": response.get("Description", "No description"),
                "Environment": response.get("Environment", {}).get("Variables", {}),
                "Architectures": response.get("Architectures", []),
            }
            return "\n".join(f"{k}: {v}" for k, v in config_info.items())
        except Exception as e:
            return f"Error getting function configuration: {str(e)}"

    def get_function_concurrency(self, function_name: str) -> str:
        """
        Get the reserved concurrency settings of a Lambda function.

        Args:
            function_name (str): The name or ARN of the Lambda function.
        """
        try:
            response = self.client.get_function_concurrency(FunctionName=function_name)
            reserved_concurrent_executions = response.get("ReservedConcurrentExecutions")
            if reserved_concurrent_executions is None:
                return "No reserved concurrency set for this function"
            return f"Reserved concurrent executions: {reserved_concurrent_executions}"
        except Exception as e:
            return f"Error getting function concurrency: {str(e)}"

    def get_function_url(self, function_name: str) -> str:
        """
        Get the function URL configuration if it exists.

        Args:
            function_name (str): The name or ARN of the Lambda function.
        """
        try:
            response = self.client.get_function_url_config(FunctionName=function_name)
            url_info = {
                "FunctionUrl": response.get("FunctionUrl"),
                "AuthType": response.get("AuthType"),
                "Cors": response.get("Cors", {}),
                "CreationTime": response.get("CreationTime"),
                "LastModifiedTime": response.get("LastModifiedTime"),
            }
            return "\n".join(f"{k}: {v}" for k, v in url_info.items())
        except Exception as e:
            return f"Error getting function URL configuration: {str(e)}"
