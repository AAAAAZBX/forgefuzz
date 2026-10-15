# ForgeFuzz 最小算术蜕变演示

演示 Triton 与 AscendC 两个后端的真实 NPU 算术蜕变闭环。原程序和蜕变程序在同一个后端、相同输入上运行，再比较各自输出。

| 后端 | 原程序 | 蜕变程序 | 验收 |
| --- | --- | --- | --- |
| Triton | `value = x + y` | `value = y + x` | 比较 1024 个 NPU float32 输出 |
| AscendC | `Sub(output5, output3, output4)` | `Muls(output5, output4, -1)` 后接 `Add(output5, output3, output5)` | 比较 64 个 NPU float32 输出 |

演示代码已拆成三个可复用脚本。两个运行脚本会依序打印 `create → generate → emit → build → run → oracle → report`，某一步失败便停止并显示失败阶段。脚本顶部注释列出功能、参数和示例；传 `--help` 可查看说明。

| 脚本 | 用途 |
| --- | --- |
| `scripts/run_triton_arithmetic_demo.sh` | 运行 Triton 加法交换律完整流程 |
| `scripts/run_ascendc_arithmetic_demo.sh` | 运行 AscendC 减法改写完整流程 |
| `scripts/summarize_arithmetic_demo.sh` | 检查两个用例报告并汇总阶段状态 |

## 演示步骤

以下命令在同一个 Bash 终端中按顺序执行。每次演示会创建新的输出目录，避免覆盖旧结果。

```bash
# 进入仓库，并检查依赖、NPU 和 CANN 环境。
cd /mnt/fangcr/zbx/forgefuzz
python main.py doctor

# 创建本次演示的独立目录；两种后端的产物都放在该目录下。
DEMO_ROOT=$(mktemp -d "$PWD/runs/arithmetic-demo-XXXXXX")
printf '演示目录：%s\n' "$DEMO_ROOT"

# 一键运行 Triton 流程：生成、发射、编译、运行、比较并生成报告。
bash scripts/run_triton_arithmetic_demo.sh "$DEMO_ROOT" 42 triton-add

# 一键运行 AscendC 流程：图中包含 Add/Sub/Mul，固定 seed 10 保持演示可复现。
bash scripts/run_ascendc_arithmetic_demo.sh "$DEMO_ROOT" 10 ascendc-sub10

# 汇总两个后端的五个核心阶段，任何失败都会返回非零状态。
bash scripts/summarize_arithmetic_demo.sh "$DEMO_ROOT/triton-add" "$DEMO_ROOT/ascendc-sub10"
```

每个脚本的参数格式也可以直接查看：

```bash
# 查看 Triton 流程脚本的用途、参数和调用示例。
bash scripts/run_triton_arithmetic_demo.sh --help

# 查看 AscendC 流程脚本的用途、参数和调用示例。
bash scripts/run_ascendc_arithmetic_demo.sh --help

# 查看汇总脚本所需的用例目录参数。
bash scripts/summarize_arithmetic_demo.sh --help
```

## 每个脚本会展示什么

Triton 脚本依序创建空用例、生成 KernelSpec 和输入、发射原程序与交换操作数的变体、编译两份 NPU 程序、使用同一批输入执行并比较输出，最后打印 `report.md`。emit 阶段还会显示规则清单和两份源码里的 `value =` 表达式。

AscendC 脚本依序创建用例、生成并打印原生图、产生 base 和 variant 工程、编译和执行两个工程、比较 float32 输出，最后打印报告。seed=10 的五节点算术图让最终减法两侧及输出均为非零值；变体直接改写最终写回 `output5` 的节点。

运行脚本支持以下参数，均可省略：

```text
bash scripts/run_triton_arithmetic_demo.sh [OUTPUT_ROOT [SEED [CASE_ID]]]
bash scripts/run_ascendc_arithmetic_demo.sh [OUTPUT_ROOT [SEED [CASE_ID]]]
```

Triton 默认 seed 是 42、case ID 是 `triton-add`；AscendC 默认 seed 是 10、case ID 是 `ascendc-sub10`。未指定输出目录时，脚本会在 `runs/` 下新建唯一目录。指定了 `OUTPUT_ROOT` 时，该目录会自动创建，但相同目录和 case ID 不能重复使用。

脚本从自身位置寻找仓库，因此可以从仓库外用绝对路径运行。也可通过 `PYTHON=/path/to/python` 指定 ForgeFuzz 使用的 Python 解释器。运行真实 NPU 流程需要上游 Triton 环境、CANN 和可访问的 Ascend 设备。

## 验收标准与结果

两个报告的 `status` 都应为 `passed`，并且 `generate`、`emit`、`build`、`run`、`oracle` 全部为 PASS。仅 `report` 阶段写出成功不代表用例通过。汇总脚本会检查这些条件。

2026-10-14 在 Ascend 910B3 / CANN 9.1.0-beta.1 上实跑：Triton 1024 个输出和 AscendC 64 个输出均为有限非零值，比较的最大绝对误差均为 0；AscendC 两个工程的 5 个输入文件逐个一致。

本工作区的示例报告：

- [Triton 报告](../runs/script-demo-cZxusn/triton-add/report.json)
- [AscendC 报告](../runs/script-demo-cZxusn/ascendc-sub10/report.json)

完整逐阶段命令已精简至 [命令清单](minimal-arithmetic-commands.md)。普通测试运行 `bash scripts/test.sh --strict`；硬件完整验收运行 `bash scripts/test.sh --hardware`。
