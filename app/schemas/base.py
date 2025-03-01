from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class MetaData(BaseModel):
    total: int = 1


class BaseSchema(BaseModel, Generic[T]):
    status: str = "success"
    meta: MetaData = MetaData()
    data: T
