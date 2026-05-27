import json
from typing import Optional

from agno.models.message import Message, MessageMetrics
from agno.utils.log import log_debug, log_error, log_info, log_warning


def log_message(
    message: Message, system_message_truncate_length: int = None, metrics: bool = True, level: Optional[str] = None
):
    """Log the message to the console

    Args:
        metrics (bool): Whether to log the metrics.
        level (str): The level to log the message at. One of debug, info, warning, or error.
            Defaults to debug.
    """
    _logger = log_debug
    if level == "info":
        _logger = log_info
    elif level == "warning":
        _logger = log_warning
    elif level == "error":
        _logger = log_error

    try:
        import shutil

        terminal_width = shutil.get_terminal_size().columns
    except Exception:
        terminal_width = 80  # fallback width

    header = f" {message.role} "
    _logger(f"{header.center(terminal_width - 20, '=')}")

    if message.name:
        _logger(f"Name: {message.name}")
    if message.tool_call_id:
        _logger(f"Tool call Id: {message.tool_call_id}")
    # V2: Use getattr for optional thinking attribute
    message_thinking = getattr(message, 'thinking', None)
    if message_thinking:
        _logger(f"<thinking>\n{message_thinking}\n</thinking>")
    if message.content:
        if isinstance(message.content, str) or isinstance(message.content, list):
            content = message.content
        elif isinstance(message.content, dict):
            content = json.dumps(message.content, indent=2)
        if message.role == "system" and system_message_truncate_length:
            content = (
                "<truncated system message>\n"
                + content[:system_message_truncate_length]
                + "\n</truncated system message>"
            )
        _logger(content)

    if message.tool_calls:
        tool_calls_list = ["Tool Calls:"]
        for tool_call in message.tool_calls:
            tool_id = tool_call.get("id")
            function_name = tool_call.get("function", {}).get("name")
            tool_calls_list.append(f"  - ID: '{tool_id}'") if tool_id else None
            tool_calls_list.append(f"    Name: '{function_name}'") if function_name else None
            tool_call_arguments = tool_call.get("function", {}).get("arguments")
            if tool_call_arguments:
                try:
                    arguments = ", ".join(f"{k}: {v}" for k, v in json.loads(tool_call_arguments).items())
                    tool_calls_list.append(f"    Arguments: '{arguments}'")
                except json.JSONDecodeError:
                    tool_calls_list.append("    Arguments: 'Invalid JSON format'")
        tool_calls_str = "\n".join(tool_calls_list)

        _logger(tool_calls_str)
    if message.images:
        _logger(f"Images added: {len(message.images)}")
    if message.videos:
        _logger(f"Videos added: {len(message.videos)}")
    if message.audio:
        _logger(f"Audio Files added: {len(message.audio)}")
    if message.files:
        _logger(f"Files added: {len(message.files)}")

    metrics_header = " TOOL METRICS " if message.role == "tool" else " METRICS "
    if metrics and message.metrics is not None and message.metrics != MessageMetrics():
        _logger(metrics_header, center=True, symbol="*")

        # Combine token metrics into a single line
        token_metrics = []
        if message.metrics.input_tokens:
            token_metrics.append(f"input={message.metrics.input_tokens}")
        if message.metrics.output_tokens:
            token_metrics.append(f"output={message.metrics.output_tokens}")
        if message.metrics.total_tokens:
            token_metrics.append(f"total={message.metrics.total_tokens}")
        if message.metrics.cached_tokens:
            token_metrics.append(f"cached={message.metrics.cached_tokens}")
        if message.metrics.reasoning_tokens:
            token_metrics.append(f"reasoning={message.metrics.reasoning_tokens}")
        if message.metrics.audio_tokens:
            token_metrics.append(f"audio={message.metrics.audio_tokens}")
        if token_metrics:
            _logger(f"* Tokens:                      {', '.join(token_metrics)}")
        if message.metrics.prompt_tokens_details:
            _logger(f"* Prompt tokens details:       {message.metrics.prompt_tokens_details}")
        if message.metrics.completion_tokens_details:
            _logger(f"* Completion tokens details:   {message.metrics.completion_tokens_details}")
        if message.metrics.time is not None:
            _logger(f"* Time:                        {message.metrics.time:.4f}s")
        if message.metrics.output_tokens and message.metrics.time:
            _logger(
                f"* Tokens per second:           {message.metrics.output_tokens / message.metrics.time:.4f} tokens/s"
            )
        if message.metrics.time_to_first_token is not None:
            _logger(f"* Time to first token:         {message.metrics.time_to_first_token:.4f}s")
        if message.metrics.additional_metrics:
            _logger(f"* Additional metrics:          {message.metrics.additional_metrics}")
        _logger(metrics_header, center=True, symbol="*")
