#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

run_hardware=0
require_upstream=0
case "${1:-}" in
  "") ;;
  --strict) require_upstream=1 ;;
  --hardware) run_hardware=1; require_upstream=1 ;;
  -h|--help)
    echo "usage: scripts/test.sh [--strict|--hardware]"
    echo "  default: syntax, unit, and lightweight real-project integration tests"
    echo "  --strict: require both upstream projects instead of allowing integration skips"
    echo "  --hardware: also run environment diagnostics and the NPU end-to-end matrix"
    exit 0
    ;;
  *)
    echo "unknown option: $1" >&2
    exit 2
    ;;
esac

echo "[1/2] compile check"
python -m compileall -q main.py fuzz tests

echo "[2/2] unit and lightweight integration tests"
if (( require_upstream )); then
  FORGEFUZZ_REQUIRE_UPSTREAM=1 python -m unittest discover -v
else
  python -m unittest discover -v
fi

if (( run_hardware )); then
  echo "[hardware 1/2] environment diagnostics"
  python main.py doctor

  echo "[hardware 2/2] Triton and AscendC NPU end-to-end matrix"
  FORGEFUZZ_RUN_HARDWARE=1 python -m unittest -v tests.test_hardware_e2e
fi
