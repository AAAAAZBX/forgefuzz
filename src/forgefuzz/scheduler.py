from __future__ import annotations

import random
from collections import Counter


class FeedbackScheduler:
    """A compact AFL-style novelty queue based on adapter-provided features."""

    def __init__(self, seed: int):
        self.rng = random.Random(seed)
        self.feature_counts: Counter[str] = Counter()
        self.failures: set[str] = set()

    def is_interesting(self, features: frozenset[str], fingerprint: str | None) -> bool:
        novel = any(self.feature_counts[x] == 0 for x in features)
        new_failure = fingerprint is not None and fingerprint not in self.failures
        self.feature_counts.update(features)
        if fingerprint:
            self.failures.add(fingerprint)
        return novel or new_failure
