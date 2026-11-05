import pytest
from pydantic import ValidationError

from agno.knowledge.page import PageSearchConfig


@pytest.mark.parametrize(
    "values",
    [
        {"ef_search": 200},
        {"statement_timeout": 10000},
        {"enable_seqscan": "off"},
        {"parallel_setup_cost": -1},
        {"parallel_tuple_cost": float("nan")},
        {"max_parallel_workers_per_gather": True},
        {"max_parallel_workers_per_gather": 1025},
        {"min_parallel_table_scan_size": -1},
        {"plan_cache_mode": "auto; SELECT 1"},
    ],
)
def test_page_search_config_rejects_invalid_or_unrelated_settings(values):
    with pytest.raises(ValidationError):
        PageSearchConfig(**values)


def test_page_search_config_defaults_leave_operator_tuning_unset():
    assert PageSearchConfig().model_dump(exclude_none=True) == {"plan_cache_mode": "force_custom_plan"}
    assert PageSearchConfig(plan_cache_mode=None).model_dump(exclude_none=True) == {}
