from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import Enum as SAEnum

JSONType = JSON().with_variant(JSONB(), "postgresql")


def enum_column(enum_cls: type, *, length: int = 64) -> SAEnum:
    return SAEnum(enum_cls, native_enum=False, length=length, validate_strings=True)
