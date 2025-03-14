from agno.models.aws.bedrock import AwsBedrock

try:
    from agno.models.aws.claude import Claude
except ImportError:

    class Claude:  # type: ignore
        def __init__(self, *args, **kwargs):
            raise ImportError("Claude requires the 'anthropic' library. Please install it via `pip install anthropic`")
