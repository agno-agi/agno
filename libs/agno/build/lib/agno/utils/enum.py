from enum import Enum
from typing import Any, List, Optional


class ExtendedEnum(Enum):
    @classmethod
    def values_list(cls: Any) -> List[Any]:
        return list(map(lambda c: c.value, cls))

    @classmethod
    def from_str(cls: Any, str_to_convert_to_enum: Optional[str]) -> Optional[Any]:
        """Convert a string value to an enum object. Case Sensitive"""

        if str_to_convert_to_enum is None:
            return None

        if str_to_convert_to_enum in cls._value2member_map_:
            return cls._value2member_map_.get(str_to_convert_to_enum)
        else:
            raise NotImplementedError(
                "{} is not a member of {}: {}".format(str_to_convert_to_enum, cls, cls._value2member_map_.keys())
            )
