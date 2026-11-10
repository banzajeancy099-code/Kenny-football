"""
Kenny Football v3.0 — Contrat des couches.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class LayerResult:
    score: float = 0.0
    confidence: float = 1.0
    warnings: list = field(default_factory=list)
    meta: dict = field(default_factory=dict)
    rejected: bool = False


class Layer:
    id: str = ""
    name: str = ""
    weight_key: str = ""

    def run(self, match: dict, ctx: dict) -> LayerResult:
        raise NotImplementedError(
            f"{self.__class__.__name__} doit implémenter run(match, ctx)"
        )
