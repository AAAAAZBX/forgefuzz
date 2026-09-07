---
name: add-forgefuzz-adapter
description: Add or complete a ForgeFuzz adapter for a language, tensor framework, compiler DSL, or hardware SDK, including its API catalog, graph generation, project emitter, metamorphic relations, oracle, and tests. Use when extending ForgeFuzz to NumPy, PyTorch, Triton, AscendC, CUDA, or another backend.
---

# Add a ForgeFuzz adapter

Build a usable backend, not a stub. Inspect the target language's APIs, constraints, build/run workflow, and available reference implementation before editing.

Read [references/adapter-contract.md](references/adapter-contract.md) before implementation. Treat `src/forgefuzz/plugin.py` and `src/forgefuzz/model.py` as the current source of truth if the reference differs.

Use `forgefuzz init <directory> --adapter-name <name>` for an external package. Built-in reference adapters belong in `src/forgefuzz/adapters/` and must be registered in `loading.py`.

Start with a small constraint-correct catalog and at least one meaningful metamorphic relation. Emit a complete standalone project beneath the supplied output directory; return commands to the framework instead of launching tools inside `emit`.

Preserve reproducibility: use only the provided `random.Random`, record input seeds in graph metadata, and make generated source deterministic. A variant must reuse the base input seed and change only what its declared relation permits.

Before finishing, run the adapter's unit tests and a short campaign. Verify a deliberately wrong output is classified as `output_mismatch`, and confirm saved base and variant programs can be run without the campaign process.
