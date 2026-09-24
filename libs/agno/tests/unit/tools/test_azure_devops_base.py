"""Unit tests for AzureDevOpsBaseTools."""

from unittest.mock import patch

import pytest

from agno.tools.azure_devops.base import AzureDevOpsBaseTools

ENV = {
    "AZURE_DEVOPS_ORG_URL": "https://dev.azure.com/org",
    "AZURE_DEVOPS_PAT": "test_pat",
    "AZURE_DEVOPS_PROJECT": "MyProject",
}


def test_init_with_params():
    tools = AzureDevOpsBaseTools(
        organization_url="https://dev.azure.com/org",
        personal_access_token="pat",
        project="Proj",
    )
    assert tools.organization_url == "https://dev.azure.com/org"
    assert tools.personal_access_token == "pat"
    assert tools.project == "Proj"


def test_init_with_env():
    with patch.dict("os.environ", ENV, clear=False):
        tools = AzureDevOpsBaseTools()
        assert tools.organization_url == "https://dev.azure.com/org"
        assert tools.project == "MyProject"


def test_init_missing_org_url_raises():
    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(ValueError):
            AzureDevOpsBaseTools(personal_access_token="pat")


def test_init_missing_pat_raises():
    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(ValueError):
            AzureDevOpsBaseTools(organization_url="https://dev.azure.com/org")


def test_resolve_project_uses_default():
    tools = AzureDevOpsBaseTools(
        organization_url="https://dev.azure.com/org", personal_access_token="pat", project="Default"
    )
    assert tools._resolve_project() == "Default"


def test_resolve_project_override():
    tools = AzureDevOpsBaseTools(
        organization_url="https://dev.azure.com/org", personal_access_token="pat", project="Default"
    )
    assert tools._resolve_project("Other") == "Other"


def test_resolve_project_missing_raises():
    tools = AzureDevOpsBaseTools(organization_url="https://dev.azure.com/org", personal_access_token="pat")
    with pytest.raises(ValueError):
        tools._resolve_project()
