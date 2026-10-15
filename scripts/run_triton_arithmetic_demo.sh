#!/usr/bin/env bash
#
# 功能：运行 Triton 加法交换律的完整算术蜕变演示。
# 参数：
#   1. OUTPUT_ROOT  可选。用例输出目录；默认在 runs/ 下创建唯一临时目录。
#   2. SEED         可选。生成器随机种子；默认 42。
#   3. CASE_ID      可选。用例名称；默认 triton-add。
# 运行示例：
#   bash scripts/run_triton_arithmetic_demo.sh
#   bash scripts/run_triton_arithmetic_demo.sh runs/my-demo 42 triton-add
# 说明：相同 OUTPUT_ROOT 和 CASE_ID 不可重复使用；每次演示请创建新的目录。
#       需要 Triton/NPU 运行环境。脚本依次执行 create、generate、emit、build、
#       run、oracle、report，任一阶段失败就停止，并打印用例目录。
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
PYTHON_BIN="${PYTHON:-python}"
OUTPUT_ROOT="${1:-}"
SEED="${2:-42}"
CASE_ID="${3:-triton-add}"

if [[ "${OUTPUT_ROOT}" == "-h" || "${OUTPUT_ROOT}" == "--help" ]]; then
  sed -n '2,13p' "$0"
  exit 0
fi
if [[ -z "$OUTPUT_ROOT" ]]; then
  mkdir -p "$PROJECT_ROOT/runs"
  OUTPUT_ROOT="$(mktemp -d "$PROJECT_ROOT/runs/triton-arithmetic-XXXXXX")"
else
  OUTPUT_ROOT="$(mkdir -p "$OUTPUT_ROOT" && cd "$OUTPUT_ROOT" && pwd)"
fi
CASE_DIR="$OUTPUT_ROOT/$CASE_ID"
cd "$PROJECT_ROOT"

# 创建空用例：固定加法模板与蜕变比较模式。
printf '\n[triton 1/7] 创建用例：%s\n' "$CASE_DIR"
"$PYTHON_BIN" main.py create --backend triton --seed "$SEED" --case-id "$CASE_ID" --output-dir "$OUTPUT_ROOT" --device npu --template elementwise_add --oracle-mode metamorphic --set equal_nan=false --timeout 600

# 生成原生 KernelSpec 和确定性输入。
printf '\n[triton 2/7] 生成程序和输入\n'
"$PYTHON_BIN" main.py stage generate "$CASE_DIR"

# 发射原程序与交换操作数后的变体，展示变换规则。
printf '\n[triton 3/7] 发射源码并展示算术变换\n'
"$PYTHON_BIN" main.py stage emit "$CASE_DIR"
"$PYTHON_BIN" -m json.tool "$CASE_DIR/configs/metamorphic.json"
grep -n 'value = ' "$CASE_DIR/source/kernel.py" "$CASE_DIR/source/variant/kernel.py"

# 分别编译原程序和蜕变程序。
printf '\n[triton 4/7] 编译两份 NPU 程序\n'
"$PYTHON_BIN" main.py stage build "$CASE_DIR"

# 在相同输入上执行两份程序并列出输出。
printf '\n[triton 5/7] 执行两份 NPU 程序\n'
"$PYTHON_BIN" main.py stage run "$CASE_DIR"
ls -lh "$CASE_DIR/outputs/triton_npu.npy" "$CASE_DIR/outputs/triton_variant_npu.npy"

# 比较两份 NPU 输出，并写入报告。
printf '\n[triton 6/7] 比较蜕变结果\n'
"$PYTHON_BIN" main.py stage oracle "$CASE_DIR"
"$PYTHON_BIN" -m json.tool "$CASE_DIR/outputs/oracle.json"
printf '\n[triton 7/7] 查看最终报告\n'
"$PYTHON_BIN" main.py stage report "$CASE_DIR"
cat "$CASE_DIR/report.md"
printf '\nTriton 用例目录：%s\n' "$CASE_DIR"
