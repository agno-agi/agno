import base64
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from agno.tools.databricks_workspace import DatabricksWorkspaceTools


class _SdkObject:
    def __init__(self, payload):
        self._payload = payload

    def as_dict(self):
        return self._payload


def test_list_workspace_objects_and_status():
    workspace_api = SimpleNamespace(
        list=lambda path, recursive: [_SdkObject({"path": f"{path}/notebook.py", "object_type": "NOTEBOOK"})],
        get_status=lambda path: _SdkObject({"path": path, "object_type": "DIRECTORY"}),
    )
    workspace_client = SimpleNamespace(workspace=workspace_api)

    tools = DatabricksWorkspaceTools(workspace_client=workspace_client)

    listed = tools.list_workspace_objects("/Users/test", limit=10)
    status = tools.get_workspace_object_status("/Users/test")

    assert json.loads(listed) == [{"path": "/Users/test/notebook.py", "object_type": "NOTEBOOK"}]
    assert json.loads(status) == {"path": "/Users/test", "object_type": "DIRECTORY"}


def test_create_directory_and_delete_workspace_object():
    workspace_api = Mock()
    workspace_client = SimpleNamespace(workspace=workspace_api)
    tools = DatabricksWorkspaceTools(workspace_client=workspace_client, enable_admin_tools=True)

    created = tools.create_directory("/Users/test/demo")
    deleted = tools.delete_workspace_object("/Users/test/demo", recursive=True)

    workspace_api.mkdirs.assert_called_once_with(path="/Users/test/demo")
    workspace_api.delete.assert_called_once_with(path="/Users/test/demo", recursive=True)
    assert json.loads(created) == {"path": "/Users/test/demo", "created": True}
    assert json.loads(deleted) == {"path": "/Users/test/demo", "deleted": True, "recursive": True}


def test_create_notebook_uses_workspace_import_with_base64_content():
    workspace_api = Mock()
    workspace_client = SimpleNamespace(workspace=workspace_api)
    workspace_service = SimpleNamespace(
        ImportFormat=SimpleNamespace(SOURCE="SOURCE"),
        Language=SimpleNamespace(PYTHON="PYTHON"),
        ExportFormat=SimpleNamespace(SOURCE="SOURCE"),
    )

    with patch("agno.tools.databricks_workspace._get_workspace_sdk", return_value=(object, workspace_service)):
        tools = DatabricksWorkspaceTools(workspace_client=workspace_client, enable_admin_tools=True)
        result = tools.create_notebook(
            path="/Users/test/demo.py",
            language="python",
            content="print('hello')",
            overwrite=True,
        )

    expected_content = base64.b64encode("print('hello')".encode("utf-8")).decode("utf-8")
    workspace_api.import_.assert_called_once_with(
        path="/Users/test/demo.py",
        content=expected_content,
        format="SOURCE",
        language="PYTHON",
        overwrite=True,
    )
    assert json.loads(result) == {"path": "/Users/test/demo.py", "created": True, "language": "PYTHON"}


def test_import_and_export_notebook():
    workspace_api = Mock()
    workspace_api.export_.return_value = _SdkObject({"content": "ZGF0YQ==", "format": "SOURCE"})
    workspace_client = SimpleNamespace(workspace=workspace_api)
    workspace_service = SimpleNamespace(
        ImportFormat=SimpleNamespace(SOURCE="SOURCE"),
        ExportFormat=SimpleNamespace(SOURCE="SOURCE"),
        Language=SimpleNamespace(SQL="SQL"),
    )

    with patch("agno.tools.databricks_workspace._get_workspace_sdk", return_value=(object, workspace_service)):
        tools = DatabricksWorkspaceTools(workspace_client=workspace_client, enable_admin_tools=True)
        imported = tools.import_notebook(
            path="/Users/test/demo.sql",
            content_base64="U0VMRUNUIDE=",
            overwrite=False,
            file_format="source",
            language="sql",
        )
        exported = tools.export_notebook("/Users/test/demo.sql")

    workspace_api.import_.assert_called_once_with(
        path="/Users/test/demo.sql",
        content="U0VMRUNUIDE=",
        format="SOURCE",
        overwrite=False,
        language="SQL",
    )
    workspace_api.export_.assert_called_once_with(path="/Users/test/demo.sql", format="SOURCE")
    assert json.loads(imported) == {"path": "/Users/test/demo.sql", "imported": True}
    assert json.loads(exported) == {"content": "ZGF0YQ==", "format": "SOURCE"}


def test_workspace_confirmation_flags():
    tools = DatabricksWorkspaceTools(workspace_client=SimpleNamespace(workspace=Mock()), enable_admin_tools=True)

    assert "create_directory" in tools.requires_confirmation_tools
    assert "create_notebook" in tools.requires_confirmation_tools
    assert "import_notebook" in tools.requires_confirmation_tools
    assert "delete_workspace_object" in tools.requires_confirmation_tools


def test_workspace_tools_hide_admin_operations_by_default():
    tools = DatabricksWorkspaceTools(workspace_client=SimpleNamespace(workspace=Mock()))

    assert "create_directory" not in tools.functions
    assert "create_notebook" not in tools.functions
    assert "import_notebook" not in tools.functions
    assert "delete_workspace_object" not in tools.functions
    assert tools.requires_confirmation_tools == []


def test_workspace_tools_reject_admin_operations_without_enable_flag():
    workspace_client = SimpleNamespace(workspace=Mock())
    workspace_service = SimpleNamespace(
        ImportFormat=SimpleNamespace(SOURCE="SOURCE"),
        Language=SimpleNamespace(PYTHON="PYTHON"),
        ExportFormat=SimpleNamespace(SOURCE="SOURCE"),
    )

    with patch("agno.tools.databricks_workspace._get_workspace_sdk", return_value=(object, workspace_service)):
        tools = DatabricksWorkspaceTools(workspace_client=workspace_client)
        create_dir_result = tools.create_directory("/Users/test/demo")
        create_notebook_result = tools.create_notebook(
            path="/Users/test/demo.py",
            language="python",
            content="print('hello')",
        )
        import_result = tools.import_notebook(path="/Users/test/demo.py", content_base64="cHJpbnQoMSk=")
        delete_result = tools.delete_workspace_object("/Users/test/demo.py")

    assert "enable_admin_tools=True" in create_dir_result
    assert "enable_admin_tools=True" in create_notebook_result
    assert "enable_admin_tools=True" in import_result
    assert "enable_admin_tools=True" in delete_result


def test_workspace_tools_require_explicit_admin_credentials_without_injected_client():
    with pytest.raises(ValueError, match="explicit admin credentials"):
        DatabricksWorkspaceTools(enable_admin_tools=True)
