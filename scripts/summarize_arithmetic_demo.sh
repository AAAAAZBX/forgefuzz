#!/usr/bin/env bash
#
# 功能：检查并汇总 Triton 与 AscendC 算术蜕变演示的最终报告。
# 参数：
#   1. TRITON_CASE_DIR  必填。Triton 用例目录，需包含 report.json。
#   2. ASCENDC_CASE_DIR 必填。AscendC 用例目录，需包含 report.json。
# 运行示例：
#   bash scripts/summarize_arithmetic_demo.sh runs/demo/triton-add runs/demo/ascendc-sub10
# 说明：两个报告均为 passed 且 generate/emit/build/run/oracle 全通过时返回 0；否则返回非零。
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
PYTHON_BIN="${PYTHON:-python}"

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  sed -n '2,11p' "$0"
  exit 0
fi
if [[ "$#" -ne 2 ]]; then
  sed -n '2,11p' "$0" >&2
  exit 2
fi
cd "$PROJECT_ROOT"

# 读取两个报告，逐项显示五个核心阶段并验证全流程状态。
"$PYTHON_BIN" - "$1" "$2" <<'PY'
import json
import sys
from pathlib import Path

required = ("generate", "emit", "build", "run", "oracle")
failed = False
for raw_path in sys.argv[1:]:
    case_dir = Path(raw_path)
    report_path = case_dir / "report.json"
    if not report_path.is_file():
        print(f"FAIL {case_dir}: report.json 不存在")
        failed = True
        continue
    report = json.loads(report_path.read_text(encoding="utf-8"))
    stages = report.get("results", {})
    status = report.get("status")
    stage_status = ", ".join(
        f"{stage}={'PASS' if stages.get(stage, {}).get('success') else 'FAIL'}"
        for stage in required
    )
    print(f"{report.get('backend', 'unknown')} {status}: {stage_status}")
    failed |= status != "passed" or any(
        not stages.get(stage, {}).get("success") for stage in required
    )
if failed:
    raise SystemExit(1)
PY
