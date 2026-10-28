"""Interface commune pour toutes les couches."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class LayerResult:
    layer_id: int
    layer_name: str
    score: float
    confidence: float
    raw: dict = field(default_factory=dict)
    features: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)
    computed_at: datetime = field(default_factory=datetime.utcnow)

    def __post_init__(self):
        self.score = max(0.0, min(10.0, self.score))
        self.confidence = max(0.0, min(1.0, self.confidence))


class BaseLayer(ABC):
    id: int = 0
    name: str = "base"

    @abstractmethod
    def compute(self, match: dict, context: dict) -> LayerResult:
        ...

    def fallback(self, match: dict, reason: str) -> LayerResult:
        return LayerResult(
            layer_id=self.id, layer_name=self.name,
            score=5.0, confidence=0.0,
            warnings=[f"fallback: {reason}"],
        )

    def safe_compute(self, match: dict, context: dict) -> LayerResult:
        try:
            return self.compute(match, context)
        except Exception as e:
            return self.fallback(match, str(e))
