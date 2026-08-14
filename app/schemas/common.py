"""Envelopes shared by every endpoint."""

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """Offset pagination. Every list endpoint returns this shape."""

    items: list[T]
    total: int = Field(description="Total matching records, ignoring limit/offset")
    limit: int
    offset: int


class ErrorDetail(BaseModel):
    code: str = Field(description="Stable machine-readable error code")
    message: str


class ErrorResponse(BaseModel):
    """One error shape for every failure, so clients need one branch."""

    error: ErrorDetail
