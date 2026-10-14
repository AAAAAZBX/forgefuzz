# Changelog

## 0.2.0

- Replace the prototype graph-adapter framework with a unified Triton/AscendC
  case pipeline.
- Add deterministic generate/emit integration, isolated build/run stages,
  common oracle results, replay, resume, reports, and environment diagnostics.
- Add sequential campaigns, per-case writer locks, upstream Git provenance,
  strict configuration validation, total stage timeout budgets, and stale-output
  cleanup.
- Validate AscendC metamorphic, compile-diff, CPU/NPU, and external-reference
  oracle paths on hardware; isolate and record required CPU-template patches.
- Add portable, strict, and real-NPU test tiers plus CI for Python 3.10 and 3.11.
