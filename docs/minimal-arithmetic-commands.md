# ForgeFuzz 算术蜕变演示：可复制命令

以下命令按顺序在同一个 Bash 终端执行。注释会随命令一起复制，说明每一步的作用。两个 NPU 流程需要真实 Triton/CANN 环境和 Ascend 设备。

```bash
# 进入仓库，检查 Triton、CANN 和 NPU 等运行环境。
cd /mnt/fangcr/zbx/forgefuzz
python main.py doctor

# 建立本次演示专用目录，避免覆盖之前的运行结果。
DEMO_ROOT=$(mktemp -d "$PWD/runs/arithmetic-demo-XXXXXX")
printf '演示目录：%s\n' "$DEMO_ROOT"

# 一键演示 Triton 的加法交换律：value = x + y 与 value = y + x。
# 参数依次是：输出根目录、随机种子、用例名称。
bash scripts/run_triton_arithmetic_demo.sh "$DEMO_ROOT" 42 triton-add

# 一键演示 AscendC 的减法改写：x - y 与 x + (-y)。
# 固定 seed=10，生成确定性的五节点算术图。
bash scripts/run_ascendc_arithmetic_demo.sh "$DEMO_ROOT" 10 ascendc-sub10

# 检查 Triton 和 AscendC 两个报告，并汇总五个核心阶段的状态。
bash scripts/summarize_arithmetic_demo.sh "$DEMO_ROOT/triton-add" "$DEMO_ROOT/ascendc-sub10"
```

第一次使用或需要了解参数时，可以单独运行以下说明命令：

```bash
# 显示 Triton 流程脚本的功能、参数和运行示例。
bash scripts/run_triton_arithmetic_demo.sh --help

# 显示 AscendC 流程脚本的功能、参数和运行示例。
bash scripts/run_ascendc_arithmetic_demo.sh --help

# 显示结果汇总脚本需要的两个用例目录参数。
bash scripts/summarize_arithmetic_demo.sh --help
```

需要单步讲解时，两个运行脚本都会为每个阶段打印步骤标题，并在终端输出 ForgeFuzz 的 PASS/FAIL 信息。源码、规则清单、设备输出和报告都保存在 `$DEMO_ROOT/<case-id>/`。
