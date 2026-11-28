from typing import Any, Dict, List


def collapse_nullable_any_of(schema: Any) -> Any:
    """Rewrite `anyOf: [X, null]` as `X` throughout a tool schema.

    The Ollama client validates each tool property against a model that keeps only `type`, `items`,
    `description` and `enum`, so an `anyOf` is dropped and the property arrives with no type at all.
    Before ollama 0.4.8 that `type` must also be a single string, so the null option cannot be kept.
    """
    if isinstance(schema, list):
        return [collapse_nullable_any_of(item) for item in schema]
    if not isinstance(schema, dict):
        return schema

    result = {key: collapse_nullable_any_of(value) for key, value in schema.items()}
    branches = result.get("anyOf")
    if isinstance(branches, list):
        non_null = [b for b in branches if not (isinstance(b, dict) and b.get("type") == "null")]
        if len(non_null) == 1 and len(non_null) < len(branches) and isinstance(non_null[0], dict):
            result.pop("anyOf")
            result = {**non_null[0], **result}
    return result


def format_tools_for_ollama(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return the tools with every function's parameter schema in a form the Ollama client keeps."""
    formatted = []
    for tool in tools:
        function = tool.get("function") if tool.get("type") == "function" else None
        if isinstance(function, dict) and isinstance(function.get("parameters"), dict):
            tool = {**tool, "function": {**function, "parameters": collapse_nullable_any_of(function["parameters"])}}
        formatted.append(tool)
    return formatted
