import json

from agno.tools.databricks_unity_catalog import DatabricksUnityCatalogTools


class _SdkObject:
    def __init__(self, payload):
        self._payload = payload

    def as_dict(self):
        return self._payload


def test_list_catalogs_serializes_sdk_objects():
    workspace_client = type("WorkspaceClient", (), {})()
    workspace_client.catalogs = type("CatalogsApi", (), {})()
    workspace_client.catalogs.list = lambda include_browse, max_results: [
        _SdkObject({"name": "main"}),
        _SdkObject({"name": "samples"}),
    ]

    tools = DatabricksUnityCatalogTools(workspace_client=workspace_client)
    result = tools.list_catalogs(limit=10)

    assert json.loads(result) == [{"name": "main"}, {"name": "samples"}]


def test_list_schemas_uses_default_catalog():
    workspace_client = type("WorkspaceClient", (), {})()
    workspace_client.schemas = type("SchemasApi", (), {})()
    captured = {}

    def _list(catalog_name, include_browse, max_results):
        captured["catalog_name"] = catalog_name
        return [_SdkObject({"full_name": f"{catalog_name}.default"})]

    workspace_client.schemas.list = _list

    tools = DatabricksUnityCatalogTools(workspace_client=workspace_client, default_catalog="main")
    result = tools.list_schemas(limit=10)

    assert captured["catalog_name"] == "main"
    assert json.loads(result) == [{"full_name": "main.default"}]


def test_list_tables_requires_catalog_and_schema():
    tools = DatabricksUnityCatalogTools(workspace_client=object())

    result = tools.list_tables()

    assert "catalog_name and schema_name are required" in result


def test_get_table_metadata_forwards_flags():
    workspace_client = type("WorkspaceClient", (), {})()
    workspace_client.tables = type("TablesApi", (), {})()
    captured = {}

    def _get(full_name, include_browse, include_delta_metadata, include_manifest_capabilities):
        captured["args"] = {
            "full_name": full_name,
            "include_browse": include_browse,
            "include_delta_metadata": include_delta_metadata,
            "include_manifest_capabilities": include_manifest_capabilities,
        }
        return _SdkObject({"full_name": full_name, "table_type": "MANAGED"})

    workspace_client.tables.get = _get

    tools = DatabricksUnityCatalogTools(workspace_client=workspace_client)
    result = tools.get_table_metadata(
        "main.analytics.events",
        include_browse=True,
        include_delta_metadata=True,
        include_manifest_capabilities=True,
    )

    assert captured["args"] == {
        "full_name": "main.analytics.events",
        "include_browse": True,
        "include_delta_metadata": True,
        "include_manifest_capabilities": True,
    }
    assert json.loads(result) == {"full_name": "main.analytics.events", "table_type": "MANAGED"}


def test_list_functions_and_volumes():
    workspace_client = type("WorkspaceClient", (), {})()
    workspace_client.functions = type("FunctionsApi", (), {})()
    workspace_client.volumes = type("VolumesApi", (), {})()
    workspace_client.functions.list = lambda catalog_name, schema_name, include_browse, max_results: [
        _SdkObject({"full_name": f"{catalog_name}.{schema_name}.fn"})
    ]
    workspace_client.volumes.list = lambda catalog_name, schema_name, include_browse, max_results: [
        _SdkObject({"full_name": f"{catalog_name}.{schema_name}.vol"})
    ]

    tools = DatabricksUnityCatalogTools(
        workspace_client=workspace_client,
        default_catalog="main",
        default_schema="analytics",
    )

    functions_result = tools.list_functions(limit=10)
    volumes_result = tools.list_volumes(limit=10)

    assert json.loads(functions_result) == [{"full_name": "main.analytics.fn"}]
    assert json.loads(volumes_result) == [{"full_name": "main.analytics.vol"}]


def test_get_function_metadata():
    workspace_client = type("WorkspaceClient", (), {})()
    workspace_client.functions = type("FunctionsApi", (), {})()
    captured = {}

    def _get(name, include_browse):
        captured["args"] = {"name": name, "include_browse": include_browse}
        return _SdkObject({"full_name": name, "routine_body": "SQL"})

    workspace_client.functions.get = _get

    tools = DatabricksUnityCatalogTools(workspace_client=workspace_client)
    result = tools.get_function_metadata("main.analytics.fn", include_browse=True)

    assert captured["args"] == {"name": "main.analytics.fn", "include_browse": True}
    assert json.loads(result) == {"full_name": "main.analytics.fn", "routine_body": "SQL"}
