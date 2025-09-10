from typing import Optional, Tuple


def parse_resource_filter(
    resource_filter: str,
) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str], Optional[str]]:
    target_env: Optional[str] = None
    target_infra: Optional[str] = None
    target_group: Optional[str] = None
    target_name: Optional[str] = None
    target_type: Optional[str] = None

    filters = resource_filter.split(":")
    num_filters = len(filters)
    if num_filters >= 1:
        if filters[0] != "":
            target_env = filters[0]
    if num_filters >= 2:
        if filters[1] != "":
            target_infra = filters[1]
    if num_filters >= 3:
        if filters[2] != "":
            target_group = filters[2]
    if num_filters >= 4:
        if filters[3] != "":
            target_name = filters[3]
    if num_filters >= 5:
        if filters[4] != "":
            target_type = filters[4]

    return target_env, target_infra, target_group, target_name, target_type
