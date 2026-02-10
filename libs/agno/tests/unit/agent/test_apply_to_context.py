"""Tests for ResolvedRunOptions.apply_to_context() — agent version."""

from pydantic import BaseModel

from agno.agent._run_options import ResolvedRunOptions
from agno.run import RunContext


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
    """When *_provided=True, the resolved value is always applied."""

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

    def test_output_schema_provided_overwrites(self):
        class Schema(BaseModel):
            x: int

        ctx = _make_context(output_schema={"old": "schema"})
        opts = _make_opts(output_schema=Schema)
        opts.apply_to_context(ctx, output_schema_provided=True)
        assert ctx.output_schema is Schema


class TestApplyFallbackWhenNone:
    """When *_provided=False and context field is None, fill from resolved defaults."""

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
    """When *_provided=False and context field is already set, leave it alone."""

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

    def test_output_schema_kept(self):
        class Existing(BaseModel):
            a: int

        class Ignored(BaseModel):
            b: int

        ctx = _make_context(output_schema=Existing)
        opts = _make_opts(output_schema=Ignored)
        opts.apply_to_context(ctx)
        assert ctx.output_schema is Existing


class TestAllFieldsTogether:
    """Apply all four fields simultaneously."""

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
            output_schema_provided=False,
        )
        # dependencies: provided=True, so overwritten
        assert ctx.dependencies == {"new": "d"}
        # knowledge_filters: provided=False, existing not None, kept
        assert ctx.knowledge_filters == {"existing": "f"}
        # metadata: provided=False, was None, filled from opts
        assert ctx.metadata == {"new": "m"}
        # output_schema: provided=False, existing not None, kept
        assert ctx.output_schema == {"existing": "schema"}
