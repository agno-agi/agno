"""Tests for ResolvedRunOptions.apply_to_context() — team version.

NOTE: apply_to_context() always sets output_schema from resolved options.
This is intentional because the same run_context may be reused across workflow
steps with different teams, each with their own output_schema.
"""

from pydantic import BaseModel

from agno.run import RunContext
from agno.team._run_options import ResolvedRunOptions


def _make_opts(**overrides) -> ResolvedRunOptions:
    defaults = dict(
        stream=False,
        stream_events=False,
        yield_run_output=False,
        add_history_to_context=False,
        add_dependencies_to_context=False,
        add_session_state_to_context=False,
        dependencies={"resolved": "deps"},
        knowledge_filters={"resolved": "filters"},
        metadata={"resolved": "meta"},
        output_schema=None,
    )
    defaults.update(overrides)
    return ResolvedRunOptions(**defaults)


def _make_context(**overrides) -> RunContext:
    defaults = dict(run_id="r1", session_id="s1")
    defaults.update(overrides)
    return RunContext(**defaults)


class TestApplyWhenProvided:
    def test_dependencies_provided_overwrites(self):
        ctx = _make_context(dependencies={"existing": "value"})
        opts = _make_opts(dependencies={"new": "value"})
        opts.apply_to_context(ctx, dependencies_provided=True)
        assert ctx.dependencies == {"new": "value"}

    def test_knowledge_filters_provided_overwrites(self):
        ctx = _make_context(knowledge_filters={"existing": "f"})
        opts = _make_opts(knowledge_filters={"new": "f"})
        opts.apply_to_context(ctx, knowledge_filters_provided=True)
        assert ctx.knowledge_filters == {"new": "f"}

    def test_metadata_provided_overwrites(self):
        ctx = _make_context(metadata={"existing": "m"})
        opts = _make_opts(metadata={"new": "m"})
        opts.apply_to_context(ctx, metadata_provided=True)
        assert ctx.metadata == {"new": "m"}

    def test_output_schema_always_set_from_opts(self):
        """Team always sets output_schema from resolved options for workflow reuse."""

        class Schema(BaseModel):
            x: int

        ctx = _make_context(output_schema={"old": "schema"})
        opts = _make_opts(output_schema=Schema)
        opts.apply_to_context(ctx)
        assert ctx.output_schema is Schema


class TestApplyFallbackWhenNone:
    def test_dependencies_none_gets_filled(self):
        ctx = _make_context(dependencies=None)
        opts = _make_opts(dependencies={"default": "deps"})
        opts.apply_to_context(ctx)
        assert ctx.dependencies == {"default": "deps"}

    def test_knowledge_filters_none_gets_filled(self):
        ctx = _make_context(knowledge_filters=None)
        opts = _make_opts(knowledge_filters={"default": "f"})
        opts.apply_to_context(ctx)
        assert ctx.knowledge_filters == {"default": "f"}

    def test_metadata_none_gets_filled(self):
        ctx = _make_context(metadata=None)
        opts = _make_opts(metadata={"default": "m"})
        opts.apply_to_context(ctx)
        assert ctx.metadata == {"default": "m"}

    def test_output_schema_none_gets_filled(self):
        class Schema(BaseModel):
            y: str

        ctx = _make_context(output_schema=None)
        opts = _make_opts(output_schema=Schema)
        opts.apply_to_context(ctx)
        assert ctx.output_schema is Schema


class TestExistingContextPreserved:
    def test_dependencies_kept(self):
        ctx = _make_context(dependencies={"keep": "me"})
        opts = _make_opts(dependencies={"ignored": "value"})
        opts.apply_to_context(ctx)
        assert ctx.dependencies == {"keep": "me"}

    def test_knowledge_filters_kept(self):
        ctx = _make_context(knowledge_filters={"keep": "f"})
        opts = _make_opts(knowledge_filters={"ignored": "f"})
        opts.apply_to_context(ctx)
        assert ctx.knowledge_filters == {"keep": "f"}

    def test_metadata_kept(self):
        ctx = _make_context(metadata={"keep": "m"})
        opts = _make_opts(metadata={"ignored": "m"})
        opts.apply_to_context(ctx)
        assert ctx.metadata == {"keep": "m"}

    def test_output_schema_always_overwritten(self):
        """Team always overwrites output_schema (unlike agent) for workflow reuse."""

        class Existing(BaseModel):
            a: int

        class NewSchema(BaseModel):
            b: int

        ctx = _make_context(output_schema=Existing)
        opts = _make_opts(output_schema=NewSchema)
        opts.apply_to_context(ctx)
        # Team always sets output_schema from opts, even if context had one
        assert ctx.output_schema is NewSchema


class TestAllFieldsTogether:
    def test_mixed_provided_and_fallback(self):
        ctx = _make_context(
            dependencies=None,
            knowledge_filters={"existing": "f"},
            metadata=None,
            output_schema={"existing": "schema"},
        )
        opts = _make_opts(
            dependencies={"new": "d"},
            knowledge_filters={"new": "f"},
            metadata={"new": "m"},
            output_schema=None,
        )
        opts.apply_to_context(
            ctx,
            dependencies_provided=True,
            knowledge_filters_provided=False,
            metadata_provided=False,
        )
        # dependencies: provided=True, so overwritten
        assert ctx.dependencies == {"new": "d"}
        # knowledge_filters: provided=False, existing not None, kept
        assert ctx.knowledge_filters == {"existing": "f"}
        # metadata: provided=False, was None, filled from opts
        assert ctx.metadata == {"new": "m"}
        # output_schema: always set from opts (team behavior for workflow reuse)
        assert ctx.output_schema is None
