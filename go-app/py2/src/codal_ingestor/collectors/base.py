from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar


T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class ScrapeRequest:
    company_name: str
    base_url: str
    pages: tuple[int, ...]
    row_limit: int


class Collector(Protocol, Generic[T]):
    def collect(self, request: ScrapeRequest) -> list[T]: ...
