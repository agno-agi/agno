from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from agno.models.aws.bedrock import AwsBedrock
from agno.models.message import Message


@dataclass
class Claude(AwsBedrock):
    """
    AWS Bedrock Claude model.

    Args:
        id (str): The model to use.
        max_tokens (int): The maximum number of tokens to generate.
        temperature (Optional[float]): The temperature to use.
        top_p (Optional[float]): The top p to use.
        top_k (Optional[int]): The top k to use.
        stop_sequences (Optional[List[str]]): The stop sequences to use.
        anthropic_version (str): The anthropic version to use.
        request_params (Optional[Dict[str, Any]]): The request parameters to use.
        client_params (Optional[Dict[str, Any]]): The client parameters to use.

    """

    id: str = "anthropic.claude-3-5-sonnet-20240620-v1:0"
    name: str = "AwsBedrockAnthropicClaude"
    provider: str = "AwsBedrock"

    # -*- Request parameters
    max_tokens: int = 4096
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    top_k: Optional[int] = None
    stop_sequences: Optional[List[str]] = None
    anthropic_version: str = "bedrock-2023-05-31"

    # -*- Request parameters
    request_params: Optional[Dict[str, Any]] = None
    # -*- Client parameters
    client_params: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        _dict = super().to_dict()
        _dict["max_tokens"] = self.max_tokens
        _dict["temperature"] = self.temperature
        _dict["top_p"] = self.top_p
        _dict["top_k"] = self.top_k
        _dict["stop_sequences"] = self.stop_sequences
        return _dict

    @property
    def api_kwargs(self) -> Dict[str, Any]:
        _request_params: Dict[str, Any] = {
            "max_tokens": self.max_tokens,
            "anthropic_version": self.anthropic_version,
        }
        if self.temperature:
            _request_params["temperature"] = self.temperature
        if self.top_p:
            _request_params["top_p"] = self.top_p
        if self.top_k:
            _request_params["top_k"] = self.top_k
        if self.stop_sequences:
            _request_params["stop_sequences"] = self.stop_sequences
        if self.request_params:
            _request_params.update(self.request_params)
        return _request_params

    def get_tools(self) -> Optional[Dict[str, Any]]:
        """
        Refactors the tools in a format accepted by the Bedrock API.
        """
        if not self._functions:
            return None

        tools = []
        for f_name, function in self._functions.items():
            properties = {}
            required = []

            for param_name, param_info in function.parameters.get("properties", {}).items():
                param_type = param_info.get("type")
                if isinstance(param_type, list):
                    param_type = [t for t in param_type if t != "null"][0]

                properties[param_name] = {
                    "type": param_type or "string",
                    "description": param_info.get("description") or "",
                }

                if "null" not in (
                    param_info.get("type") if isinstance(param_info.get("type"), list) else [param_info.get("type")]
                ):
                    required.append(param_name)

            tools.append(
                {
                    "toolSpec": {
                        "name": f_name,
                        "description": function.description or "",
                        "inputSchema": {"json": {"type": "object", "properties": properties, "required": required}},
                    }
                }
            )

        return {"tools": tools}

    def get_request_body(self, messages: List[Message]) -> Dict[str, Any]:
        """
        Get the request body for the Bedrock API.

        Args:
            messages (List[Message]): The messages to include in the request.

        Returns:
            Dict[str, Any]: The request body for the Bedrock API.
        """
        system_prompt = None
        messages_for_api = []
        for m in messages:
            if m.role == "system":
                system_prompt = m.content
            else:
                messages_for_api.append({"role": m.role, "content": [{"text": m.content}]})

        request_body = {
            "messages": messages_for_api,
            "modelId": self.id,
        }

        if system_prompt:
            request_body["system"] = [{"text": system_prompt}]

        # Add inferenceConfig
        inference_config: Dict[str, Any] = {}
        rename_map = {"max_tokens": "maxTokens", "top_p": "topP", "top_k": "topK", "stop_sequences": "stopSequences"}

        for k, v in self.api_kwargs.items():
            if k in rename_map:
                inference_config[rename_map[k]] = v
            elif k in ["temperature"]:
                inference_config[k] = v

        if inference_config:
            request_body["inferenceConfig"] = inference_config  # type: ignore

        if self.tools:
            tools = self.get_tools()
            request_body["toolConfig"] = tools  # type: ignore

        return request_body

    def parse_response_message(self, response: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parse the response from the Bedrock API.

        Args:
            response (Dict[str, Any]): The response from the Bedrock API.

        Returns:
            Dict[str, Any]: The parsed response.
        """
        res = {}
        if "output" in response and "message" in response["output"]:
            message = response["output"]["message"]
            role = message.get("role")
            content = message.get("content", [])

            # Extract text content if it's a list of dictionaries
            if isinstance(content, list) and content and isinstance(content[0], dict):
                content = [item.get("text", "") for item in content if "text" in item]
                content = "\n".join(content)  # Join multiple text items if present

            res = {
                "content": content,
                "usage": {
                    "inputTokens": response.get("usage", {}).get("inputTokens"),
                    "outputTokens": response.get("usage", {}).get("outputTokens"),
                    "totalTokens": response.get("usage", {}).get("totalTokens"),
                },
                "metrics": {"latencyMs": response.get("metrics", {}).get("latencyMs")},
                "role": role,
            }

        stop_reason = None
        if "stopReason" in response:
            stop_reason = response["stopReason"]

        res["stop_reason"] = stop_reason if stop_reason else None
        res["tool_requests"] = None

        if stop_reason == "tool_use":
            tool_requests = response["output"]["message"]["content"]
            res["tool_requests"] = tool_requests

        return res

    def create_assistant_message(self, parsed_response: Dict[str, Any]) -> Message:
        """
        Create an assistant message from the parsed response.

        Args:
            parsed_response (Dict[str, Any]): The parsed response from the Bedrock API.

        Returns:
            Message: The assistant message.
        """

        return Message(
            role=parsed_response["role"],
            content=parsed_response["content"],
            metrics=parsed_response["metrics"],
        )

    def parse_response_delta(self, response: Dict[str, Any]) -> Optional[str]:
        """
        Parse the response delta from the Bedrock API.

        Args:
            response (Dict[str, Any]): The response from the Bedrock API.

        Returns:
            Optional[str]: The response delta.
        """
        if "delta" in response:
            return response.get("delta", {}).get("text")
        return response.get("completion")
