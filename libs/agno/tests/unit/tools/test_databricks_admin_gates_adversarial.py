"""Adversarial tests for Databricks admin-gating security controls.

These tests attempt to bypass or break the admin gates that protect
mutation operations in the Databricks tools.
"""


import pytest

from agno.tools.databricks_jobs import DatabricksJobsTools
from agno.tools.databricks_jobs_admin import DatabricksJobsAdminTools
from agno.tools.databricks_tool_utils import resolve_admin_settings
from agno.tools.databricks_vector_search import DatabricksVectorSearchTools
from agno.tools.databricks_workspace import DatabricksWorkspaceTools


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakeWorkspaceClient:
    """Minimal stub that records calls instead of hitting Databricks."""

    def __init__(self):
        self.jobs = _FakeJobsApi()
        self.workspace = _FakeWorkspaceApi()
        self._calls = []


class _FakeJobsApi:
    def list(self, **kw):
        return []

    def get(self, **kw):
        return {"job_id": kw.get("job_id")}

    def list_runs(self, **kw):
        return []

    def get_run(self, **kw):
        return {"run_id": kw.get("run_id")}

    def run_now(self, **kw):
        return type("W", (), {"response": {"run_id": 42}})()

    def cancel_run(self, **kw):
        return {}

    def create(self, **kw):
        return {"job_id": 999}

    def update(self, **kw):
        return {}

    def delete(self, **kw):
        return {}

    def submit(self, **kw):
        return {"run_id": 100}


class _FakeWorkspaceApi:
    def list(self, **kw):
        return []

    def get_status(self, **kw):
        return {}

    def mkdirs(self, **kw):
        return {}

    def import_(self, **kw):
        return {}

    def export_(self, **kw):
        return {}

    def delete(self, **kw):
        return {}


class _FakeVectorSearchClient:
    """Stub for VectorSearchClient."""

    def list_endpoints(self):
        return []

    def list_indexes(self, **kw):
        return []

    def get_index(self, **kw):
        return _FakeIndex()

    def create_endpoint(self, **kw):
        return {"endpoint": kw.get("name")}

    def create_delta_sync_index(self, **kw):
        return {"index_name": kw.get("index_name")}

    def create_direct_access_index(self, **kw):
        return {"index_name": kw.get("index_name")}


class _FakeIndex:
    def describe(self):
        return {"name": "test_index"}

    def similarity_search(self, **kw):
        return {"result": []}

    def sync(self):
        return {"status": "synced"}

    def upsert(self, inputs):
        return {"status": "upserted", "count": len(inputs)}

    def delete(self, **kw):
        return {"status": "deleted"}


# ===================================================================
# 1. Direct method call bypass - admin disabled
# ===================================================================

class TestDirectMethodCallBypass:
    """Call mutation methods directly on toolkit instances with enable_admin_tools=False.

    Even if an attacker somehow obtains a reference to the method, the method
    body must refuse to execute.
    """

    def test_jobs_run_job_now_blocked(self):
        toolkit = DatabricksJobsTools(workspace_client=_FakeWorkspaceClient())
        assert toolkit.enable_admin_tools is False
        result = toolkit.run_job_now(job_id=1)
        assert "enable_admin_tools=True" in result
        assert "Error" in result

    def test_jobs_cancel_job_run_blocked(self):
        toolkit = DatabricksJobsTools(workspace_client=_FakeWorkspaceClient())
        result = toolkit.cancel_job_run(run_id=1)
        assert "enable_admin_tools=True" in result
        assert "Error" in result

    def test_workspace_create_directory_blocked(self):
        toolkit = DatabricksWorkspaceTools(workspace_client=_FakeWorkspaceClient())
        result = toolkit.create_directory(path="/test")
        assert "enable_admin_tools=True" in result
        assert "Error" in result

    def test_workspace_delete_workspace_object_blocked(self):
        toolkit = DatabricksWorkspaceTools(workspace_client=_FakeWorkspaceClient())
        result = toolkit.delete_workspace_object(path="/test")
        assert "enable_admin_tools=True" in result
        assert "Error" in result

    def test_workspace_create_notebook_blocked(self):
        toolkit = DatabricksWorkspaceTools(workspace_client=_FakeWorkspaceClient())
        result = toolkit.create_notebook(path="/test.py", language="PYTHON", content="print('hi')")
        assert "enable_admin_tools=True" in result
        assert "Error" in result

    def test_workspace_import_notebook_blocked(self):
        toolkit = DatabricksWorkspaceTools(workspace_client=_FakeWorkspaceClient())
        result = toolkit.import_notebook(path="/test.py", content_base64="dGVzdA==")
        assert "enable_admin_tools=True" in result
        assert "Error" in result

    def test_vector_search_upsert_vectors_blocked(self):
        toolkit = DatabricksVectorSearchTools(vector_search_client=_FakeVectorSearchClient())
        result = toolkit.upsert_vectors(inputs=[{"id": 1}], index_name="idx")
        assert "enable_admin_tools=True" in result
        assert "Error" in result

    def test_vector_search_delete_vectors_blocked(self):
        toolkit = DatabricksVectorSearchTools(vector_search_client=_FakeVectorSearchClient())
        result = toolkit.delete_vectors(primary_keys=[1], index_name="idx")
        assert "enable_admin_tools=True" in result
        assert "Error" in result

    def test_vector_search_create_endpoint_blocked(self):
        toolkit = DatabricksVectorSearchTools(vector_search_client=_FakeVectorSearchClient())
        result = toolkit.create_endpoint(endpoint_name="ep1")
        assert "enable_admin_tools=True" in result
        assert "Error" in result

    def test_vector_search_sync_index_blocked(self):
        toolkit = DatabricksVectorSearchTools(vector_search_client=_FakeVectorSearchClient())
        result = toolkit.sync_index(index_name="idx")
        assert "enable_admin_tools=True" in result
        assert "Error" in result

    def test_vector_search_create_delta_sync_index_blocked(self):
        toolkit = DatabricksVectorSearchTools(vector_search_client=_FakeVectorSearchClient())
        result = toolkit.create_delta_sync_index(
            index_name="idx",
            source_table_name="tbl",
            primary_key="id",
            embedding_source_column="text",
            embedding_model_endpoint_name="model",
        )
        assert "enable_admin_tools=True" in result
        assert "Error" in result

    def test_vector_search_create_direct_access_index_blocked(self):
        toolkit = DatabricksVectorSearchTools(vector_search_client=_FakeVectorSearchClient())
        result = toolkit.create_direct_access_index(
            index_name="idx",
            primary_key="id",
            embedding_dimension=128,
            embedding_vector_column="vec",
            schema={"id": "int", "vec": "array<float>"},
        )
        assert "enable_admin_tools=True" in result
        assert "Error" in result


# ===================================================================
# 2. Tool registration bypass
# ===================================================================

class TestToolRegistrationBypass:
    """Verify mutation tools are NOT registered when enable_admin_tools=False."""

    def _get_tool_names(self, toolkit):
        """Extract registered tool/function names from a toolkit."""
        return [t.__name__ if callable(t) else str(t) for t in toolkit.tools]

    def test_jobs_tools_no_admin_methods_registered(self):
        toolkit = DatabricksJobsTools(workspace_client=_FakeWorkspaceClient())
        names = self._get_tool_names(toolkit)
        assert "run_job_now" not in names
        assert "cancel_job_run" not in names

    def test_jobs_tools_requires_confirmation_empty_when_disabled(self):
        toolkit = DatabricksJobsTools(workspace_client=_FakeWorkspaceClient())
        assert toolkit.requires_confirmation_tools == [] or toolkit.requires_confirmation_tools is None

    def test_workspace_tools_no_admin_methods_registered(self):
        toolkit = DatabricksWorkspaceTools(workspace_client=_FakeWorkspaceClient())
        names = self._get_tool_names(toolkit)
        assert "create_directory" not in names
        assert "create_notebook" not in names
        assert "import_notebook" not in names
        assert "delete_workspace_object" not in names

    def test_workspace_tools_requires_confirmation_empty_when_disabled(self):
        toolkit = DatabricksWorkspaceTools(workspace_client=_FakeWorkspaceClient())
        assert toolkit.requires_confirmation_tools == [] or toolkit.requires_confirmation_tools is None

    def test_vector_search_tools_no_admin_methods_registered(self):
        toolkit = DatabricksVectorSearchTools(vector_search_client=_FakeVectorSearchClient())
        names = self._get_tool_names(toolkit)
        assert "create_endpoint" not in names
        assert "create_delta_sync_index" not in names
        assert "create_direct_access_index" not in names
        assert "sync_index" not in names
        assert "upsert_vectors" not in names
        assert "delete_vectors" not in names

    def test_vector_search_tools_requires_confirmation_empty_when_disabled(self):
        toolkit = DatabricksVectorSearchTools(vector_search_client=_FakeVectorSearchClient())
        assert toolkit.requires_confirmation_tools == [] or toolkit.requires_confirmation_tools is None

    def test_read_tools_still_registered_when_admin_disabled(self):
        """Verify read-only tools ARE still available."""
        jobs = DatabricksJobsTools(workspace_client=_FakeWorkspaceClient())
        jobs_names = self._get_tool_names(jobs)
        assert "list_jobs" in jobs_names
        assert "get_job" in jobs_names
        assert "list_job_runs" in jobs_names
        assert "get_job_run" in jobs_names

        ws = DatabricksWorkspaceTools(workspace_client=_FakeWorkspaceClient())
        ws_names = self._get_tool_names(ws)
        assert "list_workspace_objects" in ws_names
        assert "get_workspace_object_status" in ws_names
        assert "export_notebook" in ws_names

        vs = DatabricksVectorSearchTools(vector_search_client=_FakeVectorSearchClient())
        vs_names = self._get_tool_names(vs)
        assert "list_endpoints" in vs_names
        assert "list_indexes" in vs_names
        assert "describe_index" in vs_names
        assert "query_index" in vs_names


# ===================================================================
# 3. Admin client property bypass
# ===================================================================

class TestAdminClientPropertyBypass:
    """Accessing admin_client when admin is disabled should raise RuntimeError."""

    def test_jobs_admin_client_raises(self):
        toolkit = DatabricksJobsTools(workspace_client=_FakeWorkspaceClient())
        with pytest.raises(RuntimeError, match="enable_admin_tools=True"):
            _ = toolkit.admin_client

    def test_workspace_admin_client_raises(self):
        toolkit = DatabricksWorkspaceTools(workspace_client=_FakeWorkspaceClient())
        with pytest.raises(RuntimeError, match="enable_admin_tools=True"):
            _ = toolkit.admin_client

    def test_vector_search_admin_client_raises(self):
        toolkit = DatabricksVectorSearchTools(vector_search_client=_FakeVectorSearchClient())
        with pytest.raises(RuntimeError, match="enable_admin_tools=True"):
            _ = toolkit.admin_client


# ===================================================================
# 4. Credential validation
# ===================================================================

class TestCredentialValidation:
    """Test various invalid credential combinations."""

    def test_enable_admin_true_no_credentials_no_injected_client_raises(self):
        """enable_admin_tools=True but no admin credentials and no injected client."""
        with pytest.raises(ValueError, match="requires explicit admin credentials"):
            DatabricksJobsTools(enable_admin_tools=True)

    def test_partial_oauth_client_id_only_raises(self):
        """Only admin_client_id without admin_client_secret."""
        with pytest.raises(ValueError, match="both admin_client_id and admin_client_secret"):
            DatabricksJobsTools(admin_client_id="id-only", enable_admin_tools=True)

    def test_partial_oauth_client_secret_only_raises(self):
        """Only admin_client_secret without admin_client_id."""
        with pytest.raises(ValueError, match="both admin_client_id and admin_client_secret"):
            DatabricksJobsTools(admin_client_secret="secret-only", enable_admin_tools=True)

    def test_workspace_tools_partial_oauth_raises(self):
        with pytest.raises(ValueError, match="both admin_client_id and admin_client_secret"):
            DatabricksWorkspaceTools(admin_client_id="id-only", enable_admin_tools=True)

    def test_vector_search_tools_partial_oauth_raises(self):
        with pytest.raises(ValueError, match="both admin_client_id and admin_client_secret"):
            DatabricksVectorSearchTools(admin_client_id="id-only", enable_admin_tools=True)

    def test_admin_token_enables_admin(self):
        """admin_token alone should be sufficient when enable_admin_tools=True."""
        toolkit = DatabricksJobsTools(
            workspace_client=_FakeWorkspaceClient(),
            admin_token="dapi-admin-token",
            enable_admin_tools=True,
        )
        assert toolkit.enable_admin_tools is True
        assert toolkit.admin_settings is not None

    def test_oauth_pair_enables_admin(self):
        """Both admin_client_id and admin_client_secret should work."""
        toolkit = DatabricksJobsTools(
            workspace_client=_FakeWorkspaceClient(),
            admin_client_id="cid",
            admin_client_secret="csecret",
            enable_admin_tools=True,
        )
        assert toolkit.enable_admin_tools is True
        assert toolkit.admin_settings is not None

    def test_both_admin_token_and_oauth_accepted(self):
        """Both admin_token and admin_client_id/secret together should not error."""
        toolkit = DatabricksJobsTools(
            workspace_client=_FakeWorkspaceClient(),
            admin_token="dapi-tok",
            admin_client_id="cid",
            admin_client_secret="csecret",
            enable_admin_tools=True,
        )
        assert toolkit.enable_admin_tools is True

    def test_injected_client_bypasses_credential_check(self):
        """When workspace_client is injected, no credentials are required."""
        toolkit = DatabricksJobsTools(
            workspace_client=_FakeWorkspaceClient(),
            enable_admin_tools=True,
        )
        assert toolkit.enable_admin_tools is True

    def test_resolve_admin_settings_returns_none_when_disabled(self):
        result = resolve_admin_settings(
            toolkit_name="Test",
            admin_token="tok",
            admin_client_id="cid",
            admin_client_secret="csec",
            enable_admin_tools=False,
        )
        assert result is None


# ===================================================================
# 5. DatabricksJobsAdminTools specific
# ===================================================================

class TestJobsAdminToolsSpecific:
    """DatabricksJobsAdminTools must refuse instantiation without enable_admin_tools=True."""

    def test_instantiate_without_enable_admin_raises(self):
        with pytest.raises(ValueError, match="requires enable_admin_tools=True"):
            DatabricksJobsAdminTools()

    def test_instantiate_enable_admin_false_raises(self):
        with pytest.raises(ValueError, match="requires enable_admin_tools=True"):
            DatabricksJobsAdminTools(enable_admin_tools=False)

    def test_instantiate_enable_admin_true_no_creds_raises(self):
        with pytest.raises(ValueError, match="requires explicit admin credentials"):
            DatabricksJobsAdminTools(enable_admin_tools=True)

    def test_instantiate_with_injected_client_ok(self):
        toolkit = DatabricksJobsAdminTools(
            workspace_client=_FakeWorkspaceClient(),
            enable_admin_tools=True,
        )
        assert toolkit.settings is not None

    def test_all_methods_require_confirmation(self):
        toolkit = DatabricksJobsAdminTools(
            workspace_client=_FakeWorkspaceClient(),
            enable_admin_tools=True,
        )
        expected = {"create_job", "update_job", "delete_job", "submit_one_time_run"}
        actual = set(toolkit.requires_confirmation_tools or [])
        assert expected == actual


# ===================================================================
# 6. Injected client bypass
# ===================================================================

class TestInjectedClientBypass:
    """When a workspace_client is injected, verify correct client separation."""

    def test_injected_client_used_for_read_ops(self):
        read_client = _FakeWorkspaceClient()
        toolkit = DatabricksJobsTools(workspace_client=read_client)
        assert toolkit.client is read_client

    def test_injected_client_not_used_for_admin_when_disabled(self):
        read_client = _FakeWorkspaceClient()
        toolkit = DatabricksJobsTools(workspace_client=read_client)
        assert toolkit._admin_workspace_client is None
        with pytest.raises(RuntimeError):
            _ = toolkit.admin_client

    def test_injected_client_used_for_both_when_admin_enabled(self):
        shared_client = _FakeWorkspaceClient()
        toolkit = DatabricksJobsTools(
            workspace_client=shared_client,
            enable_admin_tools=True,
        )
        assert toolkit.client is shared_client
        assert toolkit.admin_client is shared_client

    def test_workspace_injected_client_not_admin_when_disabled(self):
        read_client = _FakeWorkspaceClient()
        toolkit = DatabricksWorkspaceTools(workspace_client=read_client)
        assert toolkit.client is read_client
        assert toolkit._admin_workspace_client is None

    def test_workspace_injected_client_admin_when_enabled(self):
        shared_client = _FakeWorkspaceClient()
        toolkit = DatabricksWorkspaceTools(
            workspace_client=shared_client,
            enable_admin_tools=True,
        )
        assert toolkit.client is shared_client
        assert toolkit.admin_client is shared_client

    def test_vector_search_injected_client_not_admin_when_disabled(self):
        read_client = _FakeVectorSearchClient()
        toolkit = DatabricksVectorSearchTools(vector_search_client=read_client)
        assert toolkit.client is read_client
        assert toolkit._admin_client is None

    def test_vector_search_injected_client_admin_when_enabled(self):
        shared_client = _FakeVectorSearchClient()
        toolkit = DatabricksVectorSearchTools(
            vector_search_client=shared_client,
            enable_admin_tools=True,
        )
        assert toolkit.client is shared_client
        assert toolkit.admin_client is shared_client


# ===================================================================
# 7. Requires confirmation tools list
# ===================================================================

class TestRequiresConfirmationTools:
    """Verify all mutation methods are in requires_confirmation_tools when admin is enabled."""

    def test_jobs_confirmation_tools_complete(self):
        toolkit = DatabricksJobsTools(
            workspace_client=_FakeWorkspaceClient(),
            enable_admin_tools=True,
        )
        expected = {"run_job_now", "cancel_job_run"}
        actual = set(toolkit.requires_confirmation_tools or [])
        assert expected == actual

    def test_workspace_confirmation_tools_complete(self):
        toolkit = DatabricksWorkspaceTools(
            workspace_client=_FakeWorkspaceClient(),
            enable_admin_tools=True,
        )
        expected = {"create_directory", "create_notebook", "import_notebook", "delete_workspace_object"}
        actual = set(toolkit.requires_confirmation_tools or [])
        assert expected == actual

    def test_vector_search_confirmation_tools_complete(self):
        toolkit = DatabricksVectorSearchTools(
            vector_search_client=_FakeVectorSearchClient(),
            enable_admin_tools=True,
        )
        expected = {
            "create_endpoint",
            "create_delta_sync_index",
            "create_direct_access_index",
            "sync_index",
            "upsert_vectors",
            "delete_vectors",
        }
        actual = set(toolkit.requires_confirmation_tools or [])
        assert expected == actual


# ===================================================================
# 8. The `all=True` parameter
# ===================================================================

class TestAllTrueParameter:
    """When all=True and enable_admin_tools=False, admin tools should NOT be registered."""

    def _get_tool_names(self, toolkit):
        return [t.__name__ if callable(t) else str(t) for t in toolkit.tools]

    def test_jobs_all_true_admin_disabled(self):
        toolkit = DatabricksJobsTools(workspace_client=_FakeWorkspaceClient(), all=True)
        names = self._get_tool_names(toolkit)
        # Read tools should be present
        assert "list_jobs" in names
        assert "get_job" in names
        assert "list_job_runs" in names
        assert "get_job_run" in names
        # Admin tools should NOT be present
        assert "run_job_now" not in names
        assert "cancel_job_run" not in names

    def test_workspace_all_true_admin_disabled(self):
        toolkit = DatabricksWorkspaceTools(workspace_client=_FakeWorkspaceClient(), all=True)
        names = self._get_tool_names(toolkit)
        assert "list_workspace_objects" in names
        assert "get_workspace_object_status" in names
        assert "export_notebook" in names
        # Admin tools should NOT be present
        assert "create_directory" not in names
        assert "create_notebook" not in names
        assert "import_notebook" not in names
        assert "delete_workspace_object" not in names

    def test_vector_search_all_true_admin_disabled(self):
        toolkit = DatabricksVectorSearchTools(vector_search_client=_FakeVectorSearchClient(), all=True)
        names = self._get_tool_names(toolkit)
        assert "list_endpoints" in names
        assert "list_indexes" in names
        assert "describe_index" in names
        assert "query_index" in names
        # Admin tools should NOT be present
        assert "create_endpoint" not in names
        assert "create_delta_sync_index" not in names
        assert "create_direct_access_index" not in names
        assert "sync_index" not in names
        assert "upsert_vectors" not in names
        assert "delete_vectors" not in names

    def test_jobs_all_true_admin_enabled(self):
        """With all=True AND admin enabled, admin tools SHOULD be registered."""
        toolkit = DatabricksJobsTools(
            workspace_client=_FakeWorkspaceClient(),
            enable_admin_tools=True,
            all=True,
        )
        names = self._get_tool_names(toolkit)
        assert "run_job_now" in names
        assert "cancel_job_run" in names
        assert "list_jobs" in names

    def test_workspace_all_true_admin_enabled(self):
        toolkit = DatabricksWorkspaceTools(
            workspace_client=_FakeWorkspaceClient(),
            enable_admin_tools=True,
            all=True,
        )
        names = self._get_tool_names(toolkit)
        assert "create_directory" in names
        assert "create_notebook" in names
        assert "import_notebook" in names
        assert "delete_workspace_object" in names

    def test_vector_search_all_true_admin_enabled(self):
        toolkit = DatabricksVectorSearchTools(
            vector_search_client=_FakeVectorSearchClient(),
            enable_admin_tools=True,
            all=True,
        )
        names = self._get_tool_names(toolkit)
        assert "create_endpoint" in names
        assert "create_delta_sync_index" in names
        assert "create_direct_access_index" in names
        assert "sync_index" in names
        assert "upsert_vectors" in names
        assert "delete_vectors" in names

    def test_requires_confirmation_empty_even_with_all_true_admin_disabled(self):
        """all=True should NOT add confirmation tools when admin is disabled."""
        jobs = DatabricksJobsTools(workspace_client=_FakeWorkspaceClient(), all=True)
        assert jobs.requires_confirmation_tools == [] or jobs.requires_confirmation_tools is None

        ws = DatabricksWorkspaceTools(workspace_client=_FakeWorkspaceClient(), all=True)
        assert ws.requires_confirmation_tools == [] or ws.requires_confirmation_tools is None

        vs = DatabricksVectorSearchTools(vector_search_client=_FakeVectorSearchClient(), all=True)
        assert vs.requires_confirmation_tools == [] or vs.requires_confirmation_tools is None


# ===================================================================
# 9. Additional adversarial edge cases
# ===================================================================

class TestAdversarialEdgeCases:
    """Extra edge cases to probe for security gaps."""

    def test_mutating_enable_admin_tools_after_init_does_not_unlock_tools(self):
        """Setting enable_admin_tools=True after __init__ should not add tools to the list."""
        toolkit = DatabricksJobsTools(workspace_client=_FakeWorkspaceClient())
        original_tools = list(toolkit.tools)
        # Adversarially flip the flag
        toolkit.enable_admin_tools = True
        # The tools list should NOT have changed
        assert list(toolkit.tools) == original_tools

    def test_mutating_enable_admin_tools_after_init_method_still_blocked_by_admin_client(self):
        """Even if someone flips enable_admin_tools, admin_client should not provide
        a real client since _admin_workspace_client was set to None at init."""
        toolkit = DatabricksJobsTools(workspace_client=_FakeWorkspaceClient())
        toolkit.enable_admin_tools = True
        # admin_client property will try to create a new client since _admin_workspace_client is None
        # and admin_settings is None. It should raise RuntimeError.
        with pytest.raises(RuntimeError):
            _ = toolkit.admin_client

    def test_direct_run_job_now_bypasses_gate_if_flag_flipped(self):
        """If someone flips enable_admin_tools=True after init, run_job_now's
        internal check will pass. But admin_client should still block because
        _admin_workspace_client is None and admin_settings is None."""
        toolkit = DatabricksJobsTools(workspace_client=_FakeWorkspaceClient())
        toolkit.enable_admin_tools = True
        # run_job_now checks self.enable_admin_tools, which is now True.
        # It will then try self.admin_client which should fail.
        result = toolkit.run_job_now(job_id=1)
        # Should get an error, not a successful run
        assert "Error" in result

    def test_empty_admin_token_rejected(self):
        """An empty string admin_token should not count as valid credentials."""
        with pytest.raises(ValueError, match="requires explicit admin credentials"):
            DatabricksJobsTools(admin_token="", enable_admin_tools=True)

    def test_whitespace_admin_token_rejected(self):
        """A whitespace-only admin_token should not count as valid credentials."""
        with pytest.raises(ValueError, match="requires explicit admin credentials"):
            DatabricksJobsTools(admin_token="   ", enable_admin_tools=True)
