"""Generic registry used by every factory (LLM providers, TTS, payments, mail, storage, agents, skills,
workflow steps). Implementations register themselves by name; factories create them from config."""
from __future__ import annotations

from typing import Callable, Dict, Generic, Type, TypeVar

T = TypeVar("T")


class Registry(Generic[T]):
    def __init__(self, kind: str):
        self.kind = kind
        self._items: Dict[str, Type[T]] = {}

    def register(self, name: str) -> Callable[[Type[T]], Type[T]]:
        def deco(cls: Type[T]) -> Type[T]:
            if name in self._items:
                raise ValueError(f"{self.kind} '{name}' registered twice")
            self._items[name] = cls
            return cls
        return deco

    def get(self, name: str) -> Type[T]:
        if name not in self._items:
            raise KeyError(f"unknown {self.kind} '{name}'. Known: {', '.join(sorted(self._items)) or 'none'}")
        return self._items[name]

    def create(self, name: str, *args, **kwargs) -> T:
        return self.get(name)(*args, **kwargs)

    def names(self) -> list[str]:
        return sorted(self._items)
