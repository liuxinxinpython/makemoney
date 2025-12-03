from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional

from .models import StrategyContext, StrategyDefinition, StrategyRunResult


class StrategyRegistry:
    """Central registry for research/backtest strategies."""

    def __init__(self) -> None:
        self._strategies: Dict[str, StrategyDefinition] = {}

    def register(self, definition: StrategyDefinition) -> None:
        if definition.key in self._strategies:
            raise ValueError(f"重复的策略 key: {definition.key}")
        self._strategies[definition.key] = definition

    def unregister(self, key: str) -> None:
        self._strategies.pop(key, None)

    def get(self, key: str) -> Optional[StrategyDefinition]:
        return self._strategies.get(key)

    def all(self) -> List[StrategyDefinition]:
        return list(self._strategies.values())

    def by_category(self, category: str) -> List[StrategyDefinition]:
        return [s for s in self._strategies.values() if s.category == category]

    def ensure_strategy(self, key: str) -> StrategyDefinition:
        definition = self.get(key)
        if not definition:
            raise KeyError(f"策略 {key} 未注册")
        return definition

    def run_strategy(self, key: str, context: StrategyContext) -> StrategyRunResult:
        definition = self.ensure_strategy(key)
        return definition.handler(context)


# Global registry instance for app-wide usage
_global_registry: Optional[StrategyRegistry] = None


def global_strategy_registry() -> StrategyRegistry:
    global _global_registry
    if _global_registry is None:
        _global_registry = StrategyRegistry()
    return _global_registry
