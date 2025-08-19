from typing import Any, Dict, List, Optional, Union

from agno.aws.api_client import AwsApiClient
from agno.aws.resource.secret.manager import SecretsManager


def read_secrets(
    secrets: Union[SecretsManager, List[SecretsManager]],
    aws_client: Optional[AwsApiClient] = None,
) -> Dict[str, Any]:
    secret_dict: Dict[str, str] = {}
    if secrets is not None:
        if isinstance(secrets, SecretsManager):
            _secret_dict = secrets.get_secrets_as_dict(aws_client=aws_client)
            if _secret_dict is not None and isinstance(_secret_dict, dict):
                secret_dict.update(_secret_dict)
        elif isinstance(secrets, list):
            for _secret in secrets:
                if isinstance(_secret, SecretsManager):
                    _secret_dict = _secret.get_secrets_as_dict(aws_client=aws_client)
                    if _secret_dict is not None and isinstance(_secret_dict, dict):
                        secret_dict.update(_secret_dict)
    return secret_dict
