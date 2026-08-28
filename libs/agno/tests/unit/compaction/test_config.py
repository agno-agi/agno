"""Compaction config: effective limits, init validation, record serialization."""

import pytest

from agno.compaction import Compaction, CompactionRecord
from agno.compaction.compaction import record_sort_key


class TestEffectiveLimits:
    def test_default_knobs_on_200k_window(self):
        limits = Compaction().resolve_limits(200_000)
        assert limits.reserve_eff == 16_384
        assert limits.keep_eff == 20_000
        assert limits.trigger_tokens == 170_000
        assert limits.soft_trigger_tokens == 140_000

    def test_default_knobs_on_1m_window(self):
        limits = Compaction().resolve_limits(1_000_000)
        assert limits.trigger_tokens == 850_000
        assert limits.keep_eff == 20_000

    def test_small_window_clamps_defaults_silently(self):
        # Default knobs would not fit a 32k window; they clamp instead of raising.
        limits = Compaction().resolve_limits(32_000)
        assert limits.reserve_eff == 4_000
        assert limits.keep_eff == 8_000
        assert limits.trigger_tokens == 27_200
        assert limits.trigger_tokens - limits.keep_eff >= limits.reserve_eff

    def test_explicit_keep_at_window_raises(self):
        with pytest.raises(ValueError, match="keep_recent_tokens"):
            Compaction(keep_recent_tokens=32_000).resolve_limits(32_000)

    def test_explicit_reserve_at_window_raises(self):
        with pytest.raises(ValueError, match="reserve_tokens"):
            Compaction(reserve_tokens=200_000).resolve_limits(200_000)

    def test_default_reserve_meeting_small_window_clamps(self):
        # Unset reserve (default 16_384) on a 16k window clamps to window // 8 without raising.
        limits = Compaction().resolve_limits(16_000)
        assert limits.reserve_eff == 2_000

    def test_erased_anti_thrash_gap_raises(self):
        # A tiny explicit trigger_ratio pushes the trigger below keep + reserve.
        with pytest.raises(ValueError, match="headroom"):
            Compaction(trigger_ratio=0.1).resolve_limits(200_000)

    def test_config_window_overrides_model_window(self):
        limits = Compaction(context_window=100_000).resolve_limits(200_000)
        assert limits.window == 100_000

    def test_model_window_used_when_config_unset(self):
        assert Compaction().resolve_limits(50_000).window == 50_000

    def test_fallback_window_when_nothing_known(self):
        assert Compaction().resolve_limits(None).window == 200_000

    def test_worth_it_floor(self):
        limits = Compaction().resolve_limits(200_000)
        assert limits.worth_it_floor == 2 * limits.keep_eff

    def test_soft_trigger_default_within_band(self):
        limits = Compaction().resolve_limits(200_000)
        assert limits.soft_trigger_tokens == 140_000
        assert limits.keep_eff + limits.reserve_eff <= limits.soft_trigger_tokens
        assert limits.soft_trigger_tokens <= limits.trigger_tokens - limits.reserve_eff

    def test_soft_trigger_none_when_background_off(self):
        assert Compaction(background=False).resolve_limits(200_000).soft_trigger_tokens is None

    def test_default_soft_ratio_clamps_silently_on_small_window(self):
        # On very small windows the default 0.70 soft point can leave too little gap; it clamps.
        limits = Compaction().resolve_limits(8_000)
        assert limits.soft_trigger_tokens is not None
        assert limits.keep_eff + limits.reserve_eff <= limits.soft_trigger_tokens
        assert limits.soft_trigger_tokens <= limits.trigger_tokens - limits.reserve_eff

    def test_explicit_soft_ratio_outside_band_raises(self):
        with pytest.raises(ValueError, match="background_start_ratio"):
            Compaction(background_start_ratio=0.99).resolve_limits(200_000)

    def test_explicit_soft_ratio_inside_band_kept(self):
        limits = Compaction(background_start_ratio=0.5).resolve_limits(200_000)
        assert limits.soft_trigger_tokens == 100_000

    def test_nonpositive_window_raises(self):
        with pytest.raises(ValueError, match="positive"):
            Compaction().resolve_limits(0)


class TestCompactionRecord:
    def test_round_trip(self):
        record = CompactionRecord.create("threshold", previous_id="cmp_prev", created_by_run_id="run-1")
        record.summary = "## Goal\ndo things"
        record.first_kept_run_id = "run-1"
        record.first_kept_run_index = 4
        record.first_kept_message_id = "msg-9"
        record.first_kept_message_index = 2
        record.elision_watermark_message_id = "msg-7"
        record.notice = "<context_survived>...</context_survived>"
        record.stats = {"tokens_before": 100, "tokens_after": 10}

        assert CompactionRecord.from_dict(record.to_dict()) == record

    def test_ids_and_timestamps(self):
        record = CompactionRecord.create("manual")
        assert record.id.startswith("cmp_")
        assert isinstance(record.created_at, int)
        assert record.created_by_run_id is None

    def test_deterministic_json(self):
        import json

        record = CompactionRecord.create("overflow")
        first = json.dumps(record.to_dict(), sort_keys=True)
        second = json.dumps(CompactionRecord.from_dict(record.to_dict()).to_dict(), sort_keys=True)
        assert first == second

    def test_from_dict_tolerates_missing_keys(self):
        record = CompactionRecord.from_dict({"id": "cmp_x", "created_at": 5, "reason": "manual"})
        assert record.id == "cmp_x"
        assert record.stats == {}
        assert record.summary is None

    def test_sort_key_orders_by_created_at_then_id(self):
        a = CompactionRecord(id="cmp_b", created_at=10)
        b = CompactionRecord(id="cmp_a", created_at=10)
        c = CompactionRecord(id="cmp_z", created_at=5)
        assert sorted([a, b, c], key=record_sort_key) == [c, b, a]
