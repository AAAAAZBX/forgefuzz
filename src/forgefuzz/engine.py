from __future__ import annotations

import json
import random
from collections import Counter
from dataclasses import dataclass, replace
from pathlib import Path

from .corpus import Corpus, failure_fingerprint, graph_id
from .model import ExecutionResult, FailureKind, Graph
from .mutation import AdapterMutator, GraphMutator
from .plugin import LanguageAdapter
from .runner import ProcessRunner
from .scheduler import FeedbackScheduler


@dataclass(frozen=True, slots=True)
class CampaignConfig:
    output_dir: Path
    iterations: int = 100
    seed: int = 0
    timeout_seconds: float = 30.0
    fresh_probability: float = 0.25
    metamorphic_variants: int = 1


class Campaign:
    def __init__(
        self, adapter: LanguageAdapter, config: CampaignConfig,
        mutators: tuple[GraphMutator, ...] | None = None,
    ):
        self.adapter = adapter
        self.config = config
        self.rng = random.Random(config.seed)
        self.runner = ProcessRunner()
        self.scheduler = FeedbackScheduler(config.seed)
        self.corpus = Corpus(config.output_dir / "corpus")
        self.mutators = mutators or (AdapterMutator(adapter),)

    def _execute(self, graph: Graph, case_dir: Path) -> ExecutionResult:
        errors = tuple(self.adapter.validate(graph))
        if errors:
            return ExecutionResult(FailureKind.INVALID, "validate", "; ".join(errors))
        try:
            artifact = self.adapter.emit(graph, case_dir / "program")
        except Exception as exc:
            return ExecutionResult(FailureKind.EMIT_FAILURE, "emit", str(exc))
        compile_result = None
        if artifact.compile_command:
            compile_result = self.runner.run(
                artifact.compile_command, cwd=artifact.entrypoint.parent,
                log_path=case_dir / "logs" / "compile.log",
                timeout_seconds=self.config.timeout_seconds, environment=artifact.environment,
            )
            if not compile_result.ok:
                kind = FailureKind.TIMEOUT if compile_result.timed_out else FailureKind.COMPILE_FAILURE
                fp = failure_fingerprint("compile", compile_result.log_tail)
                return ExecutionResult(kind, "compile", compile_result.log_tail[-1000:], compile=compile_result, fingerprint=fp)
        run_result = self.runner.run(
            artifact.run_command, cwd=artifact.entrypoint.parent,
            log_path=case_dir / "logs" / "run.log",
            timeout_seconds=self.config.timeout_seconds, environment=artifact.environment,
        )
        if not run_result.ok:
            kind = FailureKind.TIMEOUT if run_result.timed_out else FailureKind.RUNTIME_FAILURE
            fp = failure_fingerprint("run", run_result.log_tail)
            result = ExecutionResult(kind, "run", run_result.log_tail[-1000:], compile_result, run_result, fingerprint=fp)
        else:
            result = ExecutionResult(FailureKind.SUCCESS, "complete", compile=compile_result, run=run_result)
        try:
            result = self.adapter.oracle(artifact, result)
        except Exception as exc:
            result = ExecutionResult(
                FailureKind.INTERNAL_ERROR, "oracle", f"adapter oracle raised: {exc}",
                compile_result, run_result,
            )
        if not result.success and result.fingerprint is None:
            evidence = result.message or (result.run.log_tail if result.run else "")
            result = ExecutionResult(
                result.kind, result.stage, result.message, result.compile, result.run,
                result.features, failure_fingerprint(result.stage, evidence),
            )
        try:
            features = frozenset(self.adapter.observe(artifact, result))
        except Exception as exc:
            return ExecutionResult(
                FailureKind.INTERNAL_ERROR, "observe", f"adapter observe raised: {exc}",
                result.compile, result.run, fingerprint=failure_fingerprint("observe", str(exc)),
            )
        return ExecutionResult(result.kind, result.stage, result.message, result.compile, result.run, features, result.fingerprint)

    def replay(self, graph: Graph) -> ExecutionResult:
        """Execute one saved Graph without starting a campaign."""
        case_dir = self.config.output_dir
        case_dir.mkdir(parents=True, exist_ok=True)
        (case_dir / "graph.json").write_text(json.dumps(graph.to_dict(), indent=2), encoding="utf-8")
        result = self._execute(graph, case_dir)
        self.corpus.persist(case_dir, graph, result, interesting=False)
        return result

    def _execute_metamorphic_case(self, graph: Graph, case_dir: Path) -> ExecutionResult:
        """Run a base graph and its relation-preserving variants as one case."""
        base_dir = case_dir / "base"
        base_result = self._execute(graph, base_dir)
        if not base_result.success or self.config.metamorphic_variants <= 0:
            return base_result
        base_artifact = self.adapter.emit(graph, base_dir / "program")
        variants = list(self.adapter.metamorphic_variants(graph, self.rng))[
            : self.config.metamorphic_variants
        ]
        features = set(base_result.features)
        for variant in variants:
            variant_dir = case_dir / "variants" / variant.id
            variant_dir.mkdir(parents=True, exist_ok=True)
            (variant_dir / "graph.json").write_text(
                json.dumps(variant.graph.to_dict(), indent=2), encoding="utf-8",
            )
            (variant_dir / "transform.json").write_text(
                json.dumps({"id": variant.id, "relation": variant.relation,
                            "metadata": variant.metadata}, indent=2), encoding="utf-8",
            )
            variant_result = self._execute(variant.graph, variant_dir)
            features.update(variant_result.features)
            features.add(f"metamorphic:{variant.relation}")
            if not variant_result.success:
                return replace(variant_result, features=frozenset(features))
            variant_artifact = self.adapter.emit(variant.graph, variant_dir / "program")
            verdict = self.adapter.metamorphic_oracle(
                base_artifact, base_result, variant, variant_artifact, variant_result,
            )
            features.update(verdict.features)
            if not verdict.success:
                fingerprint = verdict.fingerprint or failure_fingerprint(
                    verdict.stage, f"{variant.relation}: {verdict.message}",
                )
                return replace(verdict, features=frozenset(features), fingerprint=fingerprint)
        return ExecutionResult(
            base_result.kind, base_result.stage, base_result.message,
            base_result.compile, base_result.run, frozenset(features), base_result.fingerprint,
        )

    def run(self) -> dict[str, int]:
        if self.config.iterations <= 0:
            raise ValueError("iterations must be positive")
        if not 0.0 <= self.config.fresh_probability <= 1.0:
            raise ValueError("fresh_probability must be between 0 and 1")
        if self.config.metamorphic_variants < 0:
            raise ValueError("metamorphic_variants must not be negative")
        self.config.output_dir.mkdir(parents=True, exist_ok=True)
        stats = Counter(success=0, failure=0, interesting=0)
        queue = self.corpus.load_graphs()
        known_ids = {graph_id(graph) for graph in queue}
        for index in range(self.config.iterations):
            generate_fresh = not queue or self.rng.random() < self.config.fresh_probability
            if not generate_fresh:
                seed_graph = self.rng.choice(queue)
                graph = self.rng.choice(self.mutators).mutate(seed_graph, self.rng)
                stats["mutated"] += 1
            else:
                graph = self.adapter.generate(self.rng)
                stats["generated"] += 1
            case_dir = self.config.output_dir / "cases" / f"id_{index:06d}"
            case_dir.mkdir(parents=True, exist_ok=True)
            (case_dir / "graph.json").write_text(json.dumps(graph.to_dict(), indent=2), encoding="utf-8")
            result = self._execute_metamorphic_case(graph, case_dir)
            interesting = self.scheduler.is_interesting(result.features, result.fingerprint)
            self.corpus.persist(case_dir, graph, result, interesting)
            if interesting and graph_id(graph) not in known_ids:
                queue.append(graph)
                known_ids.add(graph_id(graph))
            stats["success" if result.success else "failure"] += 1
            stats["interesting"] += int(interesting)
        summary = dict(stats)
        (self.config.output_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return summary
