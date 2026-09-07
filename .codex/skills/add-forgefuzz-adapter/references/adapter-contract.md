# ForgeFuzz adapter contract

## Required stages

1. `generate(rng)`: create a valid, topologically ordered `Graph` from a structured API catalog.
2. `mutate(graph, rng)`: change an op, attribute, value, shape, dtype, or topology while keeping constraints coherent.
3. `validate(graph)`: reject unknown references, arity/type/shape violations, unsupported attributes, and target limits before compilation.
4. `emit(graph, output_dir)`: write a standalone project and return `ProgramArtifact`. Put compile/run commands and environment overrides in the artifact.
5. `oracle(artifact, result)`: check a reference implementation, invariant, sanitizer result, or backend differential result.
6. `observe(artifact, result)`: expose stable novelty features such as API combinations, graph depth, compiler passes, coverage edges, and failure class.

## Metamorphic stage

Implement `metamorphic_variants(graph, rng)` and yield `MetamorphicVariant` objects. Each variant needs a stable id, a named relation, the transformed graph, and evidence describing the changed node or property. Implement `metamorphic_oracle(...)` to compare base and variant outputs with dtype/op-specific tolerance.

Safe starter relations include commutative operand swap, neutral-element insertion, inverse-pair insertion, associative regrouping (subject to floating-point tolerance), redundant cast/copy, and framework-specific equivalent APIs. Do not label a transform equivalent unless its domain preconditions are encoded and validated.

## Artifact rules

- The program must not import ForgeFuzz at runtime.
- Inputs and random seeds must be reproducible and shared by base/variants.
- Keep generated source, build files, input manifest, output, logs, and transform record in the case tree.
- Compilers and runtimes are invoked by the core runner so timeout and classification stay consistent.
- Prefer machine-readable output on the final JSON line; diagnostic text may precede it.

## Acceptance tests

- Same seed gives the same graph and emitted source.
- Generated graphs pass validation and malformed graphs fail it.
- A campaign creates `base/` and at least one `variants/<id>/transform.json`.
- Compile error, runtime error, timeout, and mismatch are distinct.
- Injected incorrect output is detected.
- A saved case and its variant are independently replayable.
