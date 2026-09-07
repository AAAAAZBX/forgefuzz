"""Public API for ForgeFuzz."""

from .engine import Campaign, CampaignConfig
from .generate import OpSpec, RandomGraphGenerator
from .model import ExecutionResult, FailureKind, Graph, MetamorphicVariant, Node, ProgramArtifact, TensorType
from .mutation import GraphMutator
from .plugin import LanguageAdapter

__all__ = [
    "Campaign",
    "CampaignConfig",
    "ExecutionResult",
    "FailureKind",
    "Graph",
    "GraphMutator",
    "LanguageAdapter",
    "MetamorphicVariant",
    "Node",
    "OpSpec",
    "ProgramArtifact",
    "RandomGraphGenerator",
    "TensorType",
]

__version__ = "0.1.0"
