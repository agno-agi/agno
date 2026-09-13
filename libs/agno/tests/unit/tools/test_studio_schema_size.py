"""The model-facing schema surface of StudioTools.

Three properties worth pinning:
1. The async variants register under the sync names, so whichever mode picks
   the entrypoint the model must see the same parameter schema.
2. The fully enabled toolkit's total schema size is budgeted: schema creep
   is a context tax on every request, so growth has to be a deliberate choice
   that moves this cap, not an accident.
3. create_workflow's steps parameter is a recursive WorkflowStepSpec; the
   schema must stay finite JSON with the recursion cut by a described stub
   (the inline contract in agno/utils/json_schema.py), not a Python cycle.
"""

import json

import pytest

from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.registry import Registry
from agno.tools.calculator import CalculatorTools
from agno.tools.studio import StudioTools

# The fully enabled surface today serializes to ~29.4k characters. The
# headroom is deliberate slack for docstring tuning, not an invitation.
SCHEMA_BUDGET_CHARS = 34000


@pytest.fixture
def studio(tmp_path):
    db = SqliteDb(id="studio-schema-db", db_file=str(tmp_path / "studio_schema.db"))
    registry = Registry(
        name="Schema Registry",
        tools=[CalculatorTools()],
        models=[OpenAIResponses(id="gpt-5.5")],
        dbs=[db],
    )
    return StudioTools(registry=registry, db=db, schedules=True)


class TestSyncAsyncParity:
    def test_every_tool_registers_sync_and_async(self, studio):
        assert set(studio.functions.keys()) == set(studio.async_functions.keys())

    def test_sync_and_async_schemas_match_for_every_tool(self, studio):
        # async_mode swaps which entrypoint serves a name; the model-facing
        # parameter schema (types, descriptions, required set) must not change
        # with it, or the async surface runs stripped of its guidance.
        mismatched = []
        for name, sync_function in studio.functions.items():
            async_function = studio.async_functions[name]
            sync_function.process_entrypoint()
            async_function.process_entrypoint()
            if sync_function.parameters != async_function.parameters:
                mismatched.append(name)
        assert mismatched == []


class TestSchemaBudget:
    def test_total_schema_size_stays_under_budget(self, studio):
        total = 0
        sizes = {}
        for name, function in studio.functions.items():
            function.process_entrypoint()
            size = len(json.dumps(function.to_dict()))
            sizes[name] = size
            total += size
        largest = sorted(sizes.items(), key=lambda item: -item[1])[:5]
        assert total < SCHEMA_BUDGET_CHARS, (
            f"Schema surface grew to {total} chars (budget {SCHEMA_BUDGET_CHARS}). "
            f"Largest tools: {largest}. Trim descriptions or move the budget deliberately."
        )


class TestWorkflowStepsSchema:
    def test_steps_schema_is_finite_json(self, studio):
        function = studio.functions["create_workflow"]
        function.process_entrypoint()
        # A recursive model naively inlined becomes a Python-level cycle;
        # json.dumps then raises instead of returning.
        serialized = json.dumps(function.parameters)
        assert "steps" in (function.parameters or {}).get("properties", {})
        assert len(serialized) < SCHEMA_BUDGET_CHARS

    def test_recursion_is_cut_by_a_described_stub(self, studio):
        function = studio.functions["create_workflow"]
        function.process_entrypoint()

        def stub_descriptions(node):
            if isinstance(node, dict):
                if "$ref" in node:
                    pytest.fail(f"un-inlined $ref left in the schema: {node['$ref']}")
                description = node.get("description")
                if isinstance(description, str) and "WorkflowStepSpec" in description and "nested" in description:
                    yield description
                for value in node.values():
                    yield from stub_descriptions(value)
            elif isinstance(node, list):
                for item in node:
                    yield from stub_descriptions(item)

        stubs = list(stub_descriptions(function.parameters))
        assert stubs, "the recursive nested-step stub must carry a description naming the model"

    def test_edit_workflow_steps_schema_is_finite_too(self, studio):
        function = studio.functions["edit_workflow"]
        function.process_entrypoint()
        json.dumps(function.parameters)
