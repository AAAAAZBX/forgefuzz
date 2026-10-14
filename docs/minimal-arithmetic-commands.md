# ForgeFuzz 算术蜕变演示命令清单

按顺序在**同一个 Bash 终端**执行，保留 `$DEMO_ROOT` 等变量。每一段开头的 `#` 注释说明这组命令的作用；整段复制到终端也可以直接运行。

## 准备环境

```bash
# 进入 ForgeFuzz 仓库，并检查 Python、Triton、CANN 和 NPU 环境。
cd /mnt/fangcr/zbx/forgefuzz
python main.py doctor

# 为本次演示创建独立目录；后续产物都会写在这里。
mkdir -p runs
DEMO_ROOT=$(mktemp -d "$PWD/runs/arithmetic-demo-XXXXXX")
TRITON_CASE="$DEMO_ROOT/triton-add"
ASCEND_CASE="$DEMO_ROOT/ascendc-sub10"
printf '%s\n' "$DEMO_ROOT"
```

## Triton：验证加法交换律 `x + y = y + x`

### 创建用例

```bash
# 创建 Triton 空用例，固定 seed、加法模板，并启用算术蜕变模式。
python main.py create --backend triton --seed 42 --case-id triton-add --output-dir "$DEMO_ROOT" --device npu --template elementwise_add --oracle-mode metamorphic --set equal_nan=false --timeout 600
```

### 生成程序和输入

```bash
# 生成 KernelSpec 和确定性输入；查看输入清单，确认输入文件名和参数。
python main.py stage generate "$TRITON_CASE"
python -m json.tool "$TRITON_CASE/inputs/manifest.json"
```

### 发射原程序与蜕变程序

```bash
# 生成两份 Triton 源码，并查看变换前后的算术表达式。
python main.py stage emit "$TRITON_CASE"
python -m json.tool "$TRITON_CASE/configs/metamorphic.json"
grep -n 'value = ' "$TRITON_CASE/source/kernel.py" "$TRITON_CASE/source/variant/kernel.py"
```

### 编译两份 NPU 程序

```bash
# 编译原程序和蜕变程序，查看每个子进程的状态。
python main.py stage build "$TRITON_CASE"
```

### 执行并查看输出

```bash
# 在相同输入上分别执行两份 NPU 程序，并列出输出文件。
python main.py stage run "$TRITON_CASE"
ls -lh "$TRITON_CASE/outputs/triton_npu.npy" "$TRITON_CASE/outputs/triton_variant_npu.npy"
```

### 比较并生成报告

```bash
# 比较原程序与蜕变程序的输出，查看比较 JSON 和人类可读报告。
python main.py stage oracle "$TRITON_CASE"
python -m json.tool "$TRITON_CASE/outputs/oracle.json"
python main.py stage report "$TRITON_CASE"
cat "$TRITON_CASE/report.md"
```

## AscendC：验证减法改写 `x - y = x + (-y)`

### 创建用例

```bash
# 创建 AscendC 空用例，固定 seed=10、5 个节点和 Add/Sub/Mul 算子。
python main.py create --backend ascendc --seed 10 --case-id ascendc-sub10 --output-dir "$DEMO_ROOT" --device npu --nodes 5 --ops Add,Sub,Mul --oracle-mode metamorphic --set ascend_arithmetic_rewrite=sub_add_neg --set equal_nan=false --timeout 600
```

### 生成并查看原生图

```bash
# 生成 AscendC graph.json，并打印图中的节点和算子。
python main.py stage generate "$ASCEND_CASE"
python -c 'import json,sys; g=json.load(open(sys.argv[1])); print(json.dumps(g["nodes"], indent=2, ensure_ascii=False))' "$ASCEND_CASE/program/graph.json"
```

### 发射工程并查看蜕变改写

```bash
# 生成 base 和 variant 两个 C++ 工程，查看规则清单及最终输出节点代码。
python main.py stage emit "$ASCEND_CASE"
python -m json.tool "$ASCEND_CASE/configs/metamorphic.json"
grep -n 'node 4\|MR: negate\|DataCopy(OutputGlobal' "$ASCEND_CASE/source/base/baremix_custom.cpp" "$ASCEND_CASE/source/variant/baremix_custom.cpp"
```

### 编译两个工程

```bash
# 分别编译原程序工程和蜕变程序工程。
python main.py stage build "$ASCEND_CASE"
```

### 执行并查看输出

```bash
# 使用相同 seed 生成输入，分别执行两份 NPU 工程并列出输出文件。
python main.py stage run "$ASCEND_CASE"
ls -lh "$ASCEND_CASE/outputs/ascend_base.bin" "$ASCEND_CASE/outputs/ascend_variant.bin"
```

### 比较并生成报告

```bash
# 比较原程序与蜕变程序的 float32 输出，查看结果和最终报告。
python main.py stage oracle "$ASCEND_CASE"
python -m json.tool "$ASCEND_CASE/outputs/oracle.json"
python main.py stage report "$ASCEND_CASE"
cat "$ASCEND_CASE/report.md"
```

## 汇总最终状态

```bash
# 检查两个用例的五个核心阶段是否全部成功；若有失败，此命令会返回非零状态。
python -c 'import json,sys; from pathlib import Path; reports=[json.loads((Path(p)/"report.json").read_text()) for p in sys.argv[1:]]; [print(r["backend"], r["status"], {k:v["success"] for k,v in r["results"].items()}) for r in reports]; assert all(r["status"] == "passed" for r in reports)' "$TRITON_CASE" "$ASCEND_CASE"
```

## 可选命令

```bash
# 重放某个用例；ForgeFuzz 会创建新目录并保留原用例。
python main.py replay "$TRITON_CASE"
python main.py replay "$ASCEND_CASE"

# 运行普通回归测试，或额外运行需要硬件的完整测试矩阵。
bash scripts/test.sh --strict
bash scripts/test.sh --hardware
```
