#!/usr/bin/env bash
#
# 功能：运行 AscendC 减法等价改写的完整算术蜕变演示。
# 参数：
#   1. OUTPUT_ROOT  可选。用例输出目录；默认在 runs/ 下创建唯一临时目录。
#   2. SEED         可选。生成器随机种子；默认 10（用于本演示的非零结果算术图）。
#   3. CASE_ID      可选。用例名称；默认 ascendc-sub10。
# 运行示例：
#   bash scripts/run_ascendc_arithmetic_demo.sh
#   bash scripts/run_ascendc_arithmetic_demo.sh runs/my-demo 10 ascendc-sub10
# 说明：相同 OUTPUT_ROOT 和 CASE_ID 不可重复使用；每次演示请创建新的目录。
#       需要 CANN/Ascend NPU 环境。脚本依次执行 create、generate、emit、build、
#       run、oracle、report，任一阶段失败就停止，并打印用例目录。
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
PYTHON_BIN="${PYTHON:-python}"
OUTPUT_ROOT="${1:-}"
SEED="${2:-10}"
CASE_ID="${3:-ascendc-sub10}"

if [[ "${OUTPUT_ROOT}" == "-h" || "${OUTPUT_ROOT}" == "--help" ]]; then
  sed -n '2,13p' "$0"
  exit 0
fi
if [[ -z "$OUTPUT_ROOT" ]]; then
  mkdir -p "$PROJECT_ROOT/runs"
  OUTPUT_ROOT="$(mktemp -d "$PROJECT_ROOT/runs/ascendc-arithmetic-XXXXXX")"
else
  OUTPUT_ROOT="$(mkdir -p "$OUTPUT_ROOT" && cd "$OUTPUT_ROOT" && pwd)"
fi
CASE_DIR="$OUTPUT_ROOT/$CASE_ID"
cd "$PROJECT_ROOT"

# 创建固定 seed/节点数/算子集合的空 AscendC 用例。
printf '\n[ascendc 1/7] 创建用例：%s\n' "$CASE_DIR"
"$PYTHON_BIN" main.py create --backend ascendc --seed "$SEED" --case-id "$CASE_ID" --output-dir "$OUTPUT_ROOT" --device npu --nodes 5 --ops Add,Sub,Mul --oracle-mode metamorphic --set ascend_arithmetic_rewrite=sub_add_neg --set equal_nan=false --timeout 600

# 调用上游图生成器并显示生成节点。
printf '\n[ascendc 2/7] 生成原生图\n'
"$PYTHON_BIN" main.py stage generate "$CASE_DIR"
"$PYTHON_BIN" -c 'import json,sys; graph=json.load(open(sys.argv[1])); print(json.dumps(graph["nodes"], indent=2, ensure_ascii=False))' "$CASE_DIR/program/graph.json"

# 发射两个 C++ 工程并展示最终输出节点的算术改写。
printf '\n[ascendc 3/7] 发射工程并展示蜕变规则\n'
"$PYTHON_BIN" main.py stage emit "$CASE_DIR"
"$PYTHON_BIN" -m json.tool "$CASE_DIR/configs/metamorphic.json"
grep -n 'node 4\|MR: negate\|DataCopy(OutputGlobal' "$CASE_DIR/source/base/baremix_custom.cpp" "$CASE_DIR/source/variant/baremix_custom.cpp"

# 分别编译原始工程和蜕变工程。
printf '\n[ascendc 4/7] 编译两个工程\n'
"$PYTHON_BIN" main.py stage build "$CASE_DIR"

# 使用相同 seed 生成输入并运行两个工程。
printf '\n[ascendc 5/7] 执行两个 NPU 工程\n'
"$PYTHON_BIN" main.py stage run "$CASE_DIR"
ls -lh "$CASE_DIR/outputs/ascend_base.bin" "$CASE_DIR/outputs/ascend_variant.bin"

# 比较原程序和蜕变程序的 float32 输出，并保存最终报告。
printf '\n[ascendc 6/7] 比较蜕变结果\n'
"$PYTHON_BIN" main.py stage oracle "$CASE_DIR"
"$PYTHON_BIN" -m json.tool "$CASE_DIR/outputs/oracle.json"
printf '\n[ascendc 7/7] 查看最终报告\n'
"$PYTHON_BIN" main.py stage report "$CASE_DIR"
cat "$CASE_DIR/report.md"
printf '\nAscendC 用例目录：%s\n' "$CASE_DIR"
