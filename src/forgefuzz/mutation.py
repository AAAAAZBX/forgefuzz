from __future__ import annotations

import random
from abc import ABC, abstractmethod

from .model import Graph
from .plugin import LanguageAdapter


class GraphMutator(ABC):
    """A small extension point for structure-aware Graph mutations."""

    name: str

    @abstractmethod
    def mutate(self, graph: Graph, rng: random.Random) -> Graph:
        """Return one mutated Graph."""


class AdapterMutator(GraphMutator):
    """Compatibility wrapper for an adapter's built-in mutation method."""

    name = "adapter"

    def __init__(self, adapter: LanguageAdapter):
        self.adapter = adapter

    def mutate(self, graph: Graph, rng: random.Random) -> Graph:
        return self.adapter.mutate(graph, rng)
