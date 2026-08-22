import os
from unittest.mock import patch

import pytest

from agno.exceptions import ModelAuthenticationError
from agno.models.openai.like import OpenAILike
from agno.models.spark import Spark
from agno.models.utils import get_model


def test_spark_initialization_with_api_key():
    model = Spark(id="generalv3.5", api_key="test-api-key")
    assert model.id == "generalv3.5"
    assert model.api_key == "test-api-key"
    assert model.base_url == "https://spark-api-open.xf-yun.com/v1"


def test_spark_initialization_without_api_key():
    with patch.dict(os.environ, {}, clear=True):
        model = Spark(id="generalv3.5")
        client_params = None
        with pytest.raises(ModelAuthenticationError):
            client_params = model._get_client_params()
        assert client_params is None


def test_spark_initialization_with_env_api_key():
    with patch.dict(os.environ, {"SPARK_API_KEY": "env-api-key"}):
        model = Spark(id="generalv3.5")
        assert model.api_key == "env-api-key"


def test_spark_client_params():
    model = Spark(id="generalv3.5", api_key="test-api-key")
    client_params = model._get_client_params()
    assert client_params["api_key"] == "test-api-key"
    assert client_params["base_url"] == "https://spark-api-open.xf-yun.com/v1"


def test_spark_client_params_delegate_to_openai_like():
    with patch.object(OpenAILike, "_get_client_params", return_value={"delegated": True}) as get_client_params:
        model = Spark(api_key="test-api-key")

        assert model._get_client_params() == {"delegated": True}
        get_client_params.assert_called_once_with()


def test_spark_default_values():
    model = Spark(api_key="test-api-key")
    assert model.id == "4.0Ultra"
    assert model.name == "Spark"
    assert model.provider == "iFLYTEK Spark"


def test_get_model_parses_spark_string():
    model = get_model("spark:4.0Ultra")
    assert isinstance(model, Spark)
    assert model.id == "4.0Ultra"
