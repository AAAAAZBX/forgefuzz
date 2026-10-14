# ForgeFuzz 最小算术蜕变闭环演示

本演示在当前工作区执行真实 Triton-Ascend 和 AscendC 后端，流程是：

`create → generate → emit（原程序＋蜕变程序）→ build → run → oracle → report`

两种语言分别验证自身原程序与蜕变程序的等价关系，不是跨语言互相比结果。

| 后端 | 原程序 | 蜕变程序 | 比较对象 |
| --- | --- | --- | --- |
| Triton | `value = x + y` | `value = y + x` | 两次 NPU 执行的 1024 个 float32 输出 |
| AscendC | 最终节点 `Sub(output5, output3, output4, active_len)` | `Muls(output5, output4, -1)`，再 `Add(output5, output3, output5)` | 两次 NPU 执行的 64 个 float32 输出 |

这里的 AscendC 蜕变直接改变最终写回的 `output5`，避免只改动不影响输出的中间节点。图中仅使用 Add/Sub/Mul；蜕变只新增乘法和加法。Triton 最小蜕变实现支持 `elementwise_add` 和 `elementwise_mul`，其他模板不匹配时会明确失败。

## 0. 准备环境和独立演示目录

以下所有命令均为单行。在**同一个 Bash 终端中按顺序复制**。每次重新演示，从这里开始，会创建新目录，不会覆盖上一次结果。

当前机器已有 Python、NumPy、两个上游项目、Triton 专用 Python 环境、CANN 和 Ascend 910B3。ForgeFuzz 使用旁边的 `triton-fuzzer-main` 和 `fuzz_code_generation`，本演示不需要重新安装依赖。

```bash
cd /mnt/fangcr/zbx/forgefuzz
python main.py doctor
mkdir -p runs
DEMO_ROOT=$(mktemp -d "$PWD/runs/arithmetic-demo-XXXXXX")
TRITON_CASE="$DEMO_ROOT/triton-add"
ASCEND_CASE="$DEMO_ROOT/ascendc-sub10"
printf '%s\n' "$DEMO_ROOT"
```

`doctor` 应显示项目、运行时、CANN 和 NPU 检查均为 OK。`DEMO_ROOT` 是这次演示的全部产物目录；后续命令使用这三个变量。

## 1. Triton：逐步展示加法交换律

### 1.1 创建空用例

固定 seed=42 和加法模板。`create` 只保存配置、建立目录，此时没有生成或执行程序。

```bash
python main.py create --backend triton --seed 42 --case-id triton-add --output-dir "$DEMO_ROOT" --device npu --template elementwise_add --oracle-mode metamorphic --set equal_nan=false --timeout 600
```

### 1.2 生成程序表示和输入

调用原项目生成器，保存 KernelSpec 和确定性随机输入。

```bash
python main.py stage generate "$TRITON_CASE"
python -m json.tool "$TRITON_CASE/inputs/manifest.json"
```

程序表示在 `program/kernel_spec.json`；输入在 `inputs/x.npy`、`inputs/y.npy`。原程序和蜕变程序读取同一目录下的输入。

### 1.3 发射两份源码并查看蜕变

保留原 emitter 产生的完整运行脚本，只在蜕变内核中交换加法的两个操作数。地址计算和 Torch 参考实现保持原样。

```bash
python main.py stage emit "$TRITON_CASE"
python -m json.tool "$TRITON_CASE/configs/metamorphic.json"
grep -n 'value = ' "$TRITON_CASE/source/kernel.py" "$TRITON_CASE/source/variant/kernel.py"
```

应看到原程序 `value = x + y`、蜕变程序 `value = y + x`。`metamorphic.json` 记录规则、前后表达式和源码行号。

### 1.4 编译两份 NPU 程序

```bash
python main.py stage build "$TRITON_CASE"
```

应显示 `base and arithmetic variant succeeded`。这是 NPU 编译；第一次运行可能需要数分钟。两个编译子进程的命令和日志分别在 `stages/build/attempt-001/triton/` 和 `triton_variant/`。

### 1.5 执行两份 NPU 程序

```bash
python main.py stage run "$TRITON_CASE"
ls -lh "$TRITON_CASE/outputs/triton_npu.npy" "$TRITON_CASE/outputs/triton_variant_npu.npy"
```

两次执行使用同一批输入。脚本也会产生 Torch 参考输出，但本次 `metamorphic` oracle 比较的是原程序 NPU 输出和蜕变程序 NPU 输出。

### 1.6 比较结果并生成报告

```bash
python main.py stage oracle "$TRITON_CASE"
python -m json.tool "$TRITON_CASE/outputs/oracle.json"
python main.py stage report "$TRITON_CASE"
cat "$TRITON_CASE/report.md"
```

预期 `mode=base_vs_metamorphic_npu`、`matches=true`、`mismatch_count=0`、`element_count=1024`，最终报告 `Status: passed`。

## 2. AscendC：逐步展示减法等价改写

### 2.1 创建空用例

固定 seed=10、5 节点、Add/Sub/Mul 算子和直接改写规则。这个种子的最终 Sub 两侧及输出均不是恒零，适合展示。上游生成器的默认控制流配置不支持本演示尝试过的 3 节点，因此使用已验证的 5 节点。

```bash
python main.py create --backend ascendc --seed 10 --case-id ascendc-sub10 --output-dir "$DEMO_ROOT" --device npu --nodes 5 --ops Add,Sub,Mul --oracle-mode metamorphic --set ascend_arithmetic_rewrite=sub_add_neg --set equal_nan=false --timeout 600
```

### 2.2 生成原生图

```bash
python main.py stage generate "$ASCEND_CASE"
python -c 'import json,sys; g=json.load(open(sys.argv[1])); print(json.dumps(g["nodes"], indent=2, ensure_ascii=False))' "$ASCEND_CASE/program/graph.json"
```

原生图是 `program/graph.json`，图示描述是 `program/graph.dot`。打印的节点算子应为 Mul、Mul、Mul、Add、Sub。

### 2.3 生成 C++ 工程并改写最终减法

```bash
python main.py stage emit "$ASCEND_CASE"
python -m json.tool "$ASCEND_CASE/configs/metamorphic.json"
grep -n 'node 4\|MR: negate\|DataCopy(OutputGlobal' "$ASCEND_CASE/source/base/baremix_custom.cpp" "$ASCEND_CASE/source/variant/baremix_custom.cpp"
```

`source/base/` 和 `source/variant/` 是独立工程。规则为 `x - y == x + (-y)`；变体把最终 Sub 改成 Muls、Add，结果仍写回 `output5`。原程序、变体的其他图节点相同。

### 2.4 编译两个工程

```bash
python main.py stage build "$ASCEND_CASE"
```

预期 `compiled 2 real AscendC project(s)`。编译日志在 `stages/build/attempt-001/compile-base/`、`compile-variant/`。

### 2.5 生成相同输入并执行两个工程

```bash
python main.py stage run "$ASCEND_CASE"
ls -lh "$ASCEND_CASE/outputs/ascend_base.bin" "$ASCEND_CASE/outputs/ascend_variant.bin"
```

两次运行用同一个 seed 和 tensor_len=64 生成输入。预期 `ran 2 real AscendC project(s)`；每份 float32 输出为 256 字节。输入文件留在两个工程各自的 `input/` 中。

### 2.6 比较结果并生成报告

```bash
python main.py stage oracle "$ASCEND_CASE"
python -m json.tool "$ASCEND_CASE/outputs/oracle.json"
python main.py stage report "$ASCEND_CASE"
cat "$ASCEND_CASE/report.md"
```

预期 `mode=metamorphic`、`relation=base_vs_metamorphic`、`matches=true`、`mismatch_count=0`、`element_count=64`，最终报告 `Status: passed`。

## 3. 汇总两个后端的最终状态

```bash
python -c 'import json,sys; from pathlib import Path; reports=[json.loads((Path(p)/"report.json").read_text()) for p in sys.argv[1:]]; [print(r["backend"], r["status"], {k:v["success"] for k,v in r["results"].items()}) for r in reports]; assert all(r["status"] == "passed" for r in reports)' "$TRITON_CASE" "$ASCEND_CASE"
```

应打印 `triton passed` 和 `ascendc passed`，五个核心阶段全部为 True。

阶段命令会自动刷新报告，因此在 oracle 完成前出现 `report written (incomplete)` 是正常的：它表示闭环尚未走完。只有最终 `report.json` 的 `status=passed` 才表示整个闭环成功；单独 `[PASS] report` 只表示报告文件成功写出。

## 4. 结果、范围与故障定位

验证环境：2026-10-14，Ascend 910B3，CANN 9.1.0-beta.1。实际验证结果见下方验收记录。

默认使用 allclose：`abs(actual-expected) <= 1e-4 + 1e-4*abs(expected)`。演示显式禁用 NaN 相等。该用例是有限输入上的算术蜕变演示，不代表全部随机图、浮点特殊值或其他算子已验证。

每条命令执行后检查 PASS/FAIL；失败时先停止向下执行。诊断看对应 `stages/<阶段>/attempt-001/` 中的 `command.json`、`stdout.log`、`stderr.log`，以及 `stages/<阶段>/result.json` 的 `failure_kind`。编译或运行失败不会当作数值不一致处理。

可选：完整重新运行保存的配置使用 `python main.py replay "$TRITON_CASE"` 或 `python main.py replay "$ASCEND_CASE"`，新结果写入新的用例目录；安装 CLI 入口不是必要条件。

可选：运行普通回归测试用 `bash scripts/test.sh --strict`；运行全部硬件验收用 `bash scripts/test.sh --hardware`，后者还包含本演示之外的 CPU/NPU 和编译选项差分测试。

## 5. 本次实际验收记录

已执行上面的逐阶段命令，两种后端均完成真实 NPU 编译和执行。

| 后端 | seed | 比较元素数 | 非零输出数 | 最大绝对误差 | 最终状态 |
| --- | --- | --- | --- | --- | --- |
| Triton 加法交换律 | 42 | 1024 | 1024 | 0 | passed |
| AscendC 最终减法改写 | 10 | 64 | 64 | 0 | passed |

两边输出全部为有限值。AscendC 原程序和变体的 5 个输入二进制文件逐个比较完全相同。

本工作区保存的实际报告（`runs/` 是忽略版本管理的运行产物）：

- [Triton 报告](../runs/arithmetic-demo-24YSPg/triton-add/report.json)
- [Triton 比较结果](../runs/arithmetic-demo-24YSPg/triton-add/outputs/oracle.json)
- [AscendC 报告](../runs/arithmetic-demo-24YSPg/ascendc-sub10/report.json)
- [AscendC 比较结果](../runs/arithmetic-demo-24YSPg/ascendc-sub10/outputs/oracle.json)

`bash scripts/test.sh --strict`：44 项测试，38 项通过、6 项硬件测试按默认策略跳过。
本节两条 NPU 路径是在普通测试之外实际执行的；没有声称完整 `--hardware` 矩阵已运行。
回归测试还覆盖了两个后端的输出篡改检测，确认错误结果会返回 `oracle_mismatch`，而不是无条件通过。

本次代码补充：`create` 空用例命令、Triton 算术交换律双程序执行与比较、AscendC 最终输出减法直接改写，以及对应回归测试。原来的 Torch oracle 和 AscendC 通用注入路径仍可使用。
