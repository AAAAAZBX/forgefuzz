# ForgeFuzz

ForgeFuzz 是 Triton-Ascend 与 AscendC fuzz 项目的统一执行外壳。它统一 case 生命周期、阶段协议、日志、失败分类和重放方式，但保留两个后端各自成熟的程序表示：

- Triton 后端继续使用旧项目的 `KernelSpec`；
- AscendC 后端继续使用旧项目的 `graph.json`；
- 公共层只调度 `generate → emit → build → run → oracle → report`。

这里没有把两种语言塞进一个损失语义的统一 IR，也没有用固定数组或模拟成功替代真实工具链。缺少依赖、CANN 或设备时，阶段会失败并记录可操作的诊断。

只演示算术蜕变最小闭环时，参见 [逐行命令演示](docs/minimal-arithmetic-demo.md)。
该演示使用真实 NPU，Triton 验证加法交换律，AscendC 改写最终输出的减法节点。
新增 `create` 命令支持从空用例开始逐阶段执行；Triton 的 `metamorphic` 模式支持
`elementwise_add` / `elementwise_mul`，AscendC 可通过
`--set ascend_arithmetic_rewrite=sub_add_neg` 选择最小直接改写。

## 目录

- [当前状态](#当前状态)
- [快速开始](#快速开始)
- [架构](#架构)
  - [阶段职责](#阶段职责)
- [Case 目录](#case-目录)
- [CLI](#cli)
  - [运行完整流程](#运行完整流程)
  - [批量 Campaign](#批量-campaign)
  - [单阶段、继续和重放](#单阶段继续和重放)
- [配置](#配置)
- [Oracle 模式](#oracle-模式)
- [失败分类](#失败分类)
- [后端真实接入与代码映射](#后端真实接入与代码映射)
- [新增后端](#新增后端)
- [开发与测试](#开发与测试)
- [已知限制](#已知限制)

## 当前状态

当前实现已在本工作区的真实旧项目和 Ascend NPU 环境验证：

- Triton：真实 `KernelSpec` 生成、NumPy 输入生成、Triton Python 发射、NPU 编译/执行、Torch/NPU allclose 均通过；
- Triton interpreter：真实 interpreter 与 Torch reference 比较通过；
- AscendC：真实图生成、C++/工程生成、base 与蜕变 variant 编译、NPU 执行及输出比较均通过；
- 公共层：成功、失败停止、异常转换、超时、落盘、单阶段、resume 和 replay 已有自动测试。

本机验证矩阵：

| 能力 | 状态 |
| --- | --- |
| Triton generate/emit 确定性 | 自动测试通过 |
| Triton interpreter + Torch oracle | 真实运行通过 |
| Triton NPU compile/run + Torch oracle | 真实运行通过 |
| AscendC generate/emit 确定性 | 自动测试通过 |
| AscendC metamorphic 双工程 NPU compile/run/oracle | 真实运行通过 |
| AscendC compile_diff 双工程 NPU oracle | 真实运行通过 |
| AscendC CPU/NPU oracle | 真实运行通过；适配器记录两处上游 CPU 模板兼容补丁 |
| AscendC external oracle | 真实运行通过；reference 被复制并校验到 case |
| AscendC 缺失 CANN 分类 | 自动测试通过 |
| AscendC golden oracle | 默认模板 golden 为 16 个 float，而默认输出为 64 个 float；仅在调用方确认语义和 shape 时使用 |

验证不表示所有 Triton profile、AscendC 算子、CANN 版本和 oracle 组合都已穷举。参见“已知限制”。

## 快速开始

要求 Python 3.10+。公共框架只使用标准库；真实后端沿用旧项目依赖。当前工作区自动发现：

```text
../triton-fuzzer-main
../fuzz_code_generation
```

先诊断环境：

```bash
python main.py doctor
```

只诊断某个后端时使用 `--backend triton|ascendc`。例如 interpreter 环境无需
CANN 或 NPU：

```bash
python main.py doctor --backend triton --device interpreter
```

运行真实 Triton NPU case：

```bash
python main.py run --backend triton --seed 42 --device npu
```

运行 Triton interpreter（不要求 NPU 编译）：

```bash
python main.py run --backend triton --seed 42 --device interpreter
```

运行真实 AscendC base/variant 蜕变 case：

```bash
python main.py run \
  --backend ascendc \
  --seed 42 \
  --device npu \
  --oracle-mode metamorphic
```

旧原型命令仍兼容：

```bash
python main.py --backend triton --seed 42 --device interpreter
```

命令成功返回 0；任何核心阶段失败返回 1；参数、配置或阶段前置条件错误返回 2。

## 架构

```text
CLI / JSON or TOML config
            │
            ▼
      CaseBundle + CaseContext
            │
            ▼
 generate → emit → build → run → oracle
    │         │       │       │       │
    └──────── Backend contract ────────┘
            │
            ▼
     common report.json/report.md
```

公共代码不包含 `if backend == ...` 的阶段逻辑。CLI 只在创建 case 时选择适配器；短小的 pipeline 按统一接口调用后端。

### 阶段职责

| 阶段 | 公共约定 | Triton | AscendC |
| --- | --- | --- | --- |
| `generate` | 原生表示和确定性输入 | 旧项目 `ConstructiveGenerator` 产生 `KernelSpec`、generation trace 和真实 NumPy 输入 | 调用 `generate_graph.py` 产生真实 `graph.json`/DOT |
| `emit` | 原生表示降为源码 | `TritonPythonEmitter` 产生自包含 Python harness | `execute_graph.py` + `split_cpp_sections.py` 产生 baremix C++ 工程；按 oracle 模式生成第二工程 |
| `build` | 编译或解释器前置校验 | NPU 模式调用 harness `compile`；interpreter 模式做真实语法校验 | 对 base/reference/variant 分别调用 `compile.sh` |
| `run` | 真实执行和输出收集 | harness 执行 Torch reference 及 NPU/interpreter 目标 | 分别调用 `run_once.sh`，输入 seed 经环境变量传入旧生成器 |
| `oracle` | 只比较已成功产生的输出 | Torch vs NPU/interpreter，exact 或 allclose | base/variant、NPU/CPU、编译选项差分、golden 或外部参考 |
| `report` | 公共汇总 | 统一 `report.json`、文件 hash 清单和 replay 命令 | 同左 |

更详细的边界见 [docs/architecture.md](docs/architecture.md) 和 [docs/backend-integration.md](docs/backend-integration.md)。

## Case 目录

每个 case 完全隔离：

```text
runs/<case-id>/
├── case.json                    # seed、解析后配置、最新阶段结果、尝试历史
├── program/                     # KernelSpec 或 graph.json
├── inputs/                      # 可重放输入及 manifest
├── source/                      # Triton harness 或 AscendC 工程
├── configs/                     # resolved config、迁移/注入 manifest
├── stages/
│   ├── generate/attempt-001/
│   ├── emit/attempt-001/
│   ├── build/attempt-001/
│   ├── run/attempt-001/
│   ├── oracle/attempt-001/
│   └── report/attempt-001/
├── outputs/                     # 设备、参考、IR 和 oracle 结果
├── cache/                       # case 私有 Triton/Python 缓存
├── report.json
└── report.md
```

每个外部命令保存：

- `command.json`：参数列表、cwd 和显式环境覆盖；
- `stdout.log` / `stderr.log`；
- exit code、耗时和 timeout 状态；
- 阶段目录下的 `result.json`。

阶段重跑不会删除旧 attempt；最新结果另写到 `stages/<stage>/result.json`。Triton cache、dump 和 Python bytecode 都重定向到 case，旧项目不会收到运行缓存。

## CLI

### 运行完整流程

```bash
python main.py run --backend triton --seed 42
python main.py run --backend ascendc --seed 42
```

常用选项：

```text
--config FILE                 JSON 或 Python 3.11+ 下的 TOML
--output-dir PATH             case 根目录
--timeout SECONDS             默认阶段超时
--device npu|cpu|sim|interpreter
--oracle-mode MODE
--comparison exact|allclose
--atol FLOAT --rtol FLOAT
--triton-root PATH
--triton-python PATH
--ascendc-root PATH
--cann-path PATH
--set KEY=JSON                覆盖高级配置
```

Triton 专用：

```bash
python main.py run --backend triton --seed 7 \
  --profile P5 --template mixed_dag \
  --set triton_semantic_api_count=5
```

AscendC 专用：

```bash
python main.py run --backend ascendc --seed 7 \
  --nodes 12 --ops Add,Mul,Sub,Abs,Relu \
  --set ascend_tensor_len=64 \
  --set ascend_soc_version=Ascend910B3
```

### 批量 Campaign

按连续 seed 顺序运行隔离 case，并持续更新 `campaign.json`：

```bash
python main.py campaign --backend triton --device interpreter \
  --start-seed 0 --count 100
python main.py campaign --backend ascendc --device npu \
  --start-seed 0 --count 20 --stop-on-failure
```

每个 case 仍保留完整阶段日志和报告。当前 campaign 是可靠的顺序批处理，不包含
coverage 引导、自动规约或并行 worker。

### 单阶段、继续和重放

```bash
python main.py stage oracle runs/<case-id>
python main.py resume runs/<case-id> --from build
python main.py replay runs/<case-id>
```

- `stage` 要求前一阶段已成功；它只运行指定阶段，然后刷新报告。
- `resume` 从指定阶段继续，保留更早阶段和所有历史 attempt。
- `replay` 从原 case 的 seed 和解析后配置创建一个新 case，不覆盖原失败现场；结束时比较原生程序表示 SHA-256 并报告是否复现。

## 配置

JSON 示例：

```json
{
  "timeout": 180,
  "stage_timeouts": {"build": 300, "run": 180},
  "device": "npu",
  "oracle_mode": "metamorphic",
  "comparison": "allclose",
  "atol": 0.0001,
  "rtol": 0.0001,
  "equal_nan": true,
  "triton_root": "../triton-fuzzer-main",
  "triton_python": "../triton-fuzzer-main/.envs/triton-ascend/bin/python",
  "ascendc_root": "../fuzz_code_generation",
  "ascend_cann_path": "/usr/local/Ascend/ascend-toolkit/latest",
  "ascend_run_mode": "npu",
  "ascend_soc_version": "Ascend910B3"
}
```

相对路径按启动进程当前目录解析，最终绝对路径保存到 `configs/resolved.json`。CLI 覆盖配置文件，`--set` 的值优先按 JSON 解析。

## Oracle 模式

比较策略统一支持：

- `exact`：逐元素精确相等，可配置 `equal_nan`；
- `allclose`：`abs(actual - expected) <= atol + rtol * abs(expected)`；
- shape、dtype（`.npy`）或 float32 二进制格式错误单独分类。

Triton 的 `metamorphic` 模式比较原程序与蜕变程序的设备输出；`auto` / `torch` 模式中，reference 由旧 emitter 在目标运行后用 Torch CPU 真实计算。`--device npu` 比较 Torch/NPU；`--device interpreter` 比较 Torch/Triton interpreter。

AscendC 模式：

| 模式 | 第二路径 | 比较 |
| --- | --- | --- |
| `metamorphic`（`auto` 默认） | 旧 `inject_and_generate.py` 产生 chain-foldback variant | base vs variant NPU 输出 |
| `cpu_npu` | 同源工程按 `ascend_reference_run_mode=cpu` 编译 | CPU reference vs 目标输出 |
| `compile_diff` | 同源工程使用 `ascend_variant_flags` 编译 | 默认编译 vs 修改选项 |
| `golden` | baremix 输入生成器产生的 `golden.bin` | template golden vs 输出；仅适合其 golden 语义确实匹配的 case |
| `external` | `reference_output` 指向外部 float32 binary | 外部参考 vs 输出 |

编译或运行失败会在 oracle 之前停止，不会被误报为数值 bug。输出缺失、格式错误、reference 失败、target 失败和数值不一致分别记录。

## 失败分类

`StageResult.failure_kind` 的主要值：

```text
generation_failure   emission_failure    compile_failure
runtime_failure      target_failure      reference_failure
oracle_mismatch      output_missing      output_format_error
timeout              dependency_missing  environment_missing
invalid_case         internal_error
```

unexpected Python 异常统一转换成 `internal_error` 并持久化；子进程 timeout 会终止整个进程组。

## 后端真实接入与代码映射

当前工作区实际 Triton 目录是 `triton-fuzzer-main/`。两个旧项目均只读使用。

| 阶段 | Triton 来源 | AscendC 来源 |
| --- | --- | --- |
| generate | `triton_ascend_fuzz/generate/generator.py`、`generate/inputs.py`、`spec/model.py` | `generate_graph.py` |
| emit | `triton_ascend_fuzz/emit/triton_python.py` | `execute_graph.py`、`split_cpp_sections.py`、`baremix/` 模板 |
| build | emitter 生成 harness 的 `--mode compile`；隔离策略参考 `execute/subprocess_runner.py` | `baremix/compile.sh` |
| run | emitter 生成 harness 的 `--mode run/interpreter` | `baremix/run_once.sh` |
| oracle | `oracle/compare.py` 的 exact/allclose 语义；Torch reference 由 harness 生成 | `metamorphic/inject_and_generate.py`、`count_bin_abs_diff.py`、`scripts/verify_result.py` 的 float32 比较语义 |

ForgeFuzz 没有复制旧仓库。AscendC 每个 case 只物化构建所需的 baremix 模板文件和约 24KB 的 `ops` 普通头文件，来源写入 `configs/ascend_source_manifest.json`；不会复制旧 build/output/cache 或自指符号链接。

## 新增后端

1. 在 `fuzz/backends/` 新建类并实现 `Backend` 的五个方法；
2. 每个方法只写当前 case，返回统一 `StageResult`；
3. 外部进程通过 `ProcessRunner` 执行，传参数列表并设置独立 timeout；
4. 在 `fuzz/cli.py` 的 `BACKENDS` 注册实例；
5. 添加 contract、失败、缺依赖和确定性测试。

不需要修改 `pipeline.py`，也不需要把新语言转换为 Triton 或 AscendC 表示。

## 开发与测试

统一测试入口：

```bash
bash scripts/test.sh
```

该命令执行语法检查、公共层单元测试，以及两个真实旧项目的 generate/emit
确定性集成测试；不需要 NPU。普通模式允许不存在的旧项目测试被跳过；交付前可用
严格模式要求两个项目必须存在：

```bash
bash scripts/test.sh --strict
```

运行包括环境诊断、Triton NPU、AscendC metamorphic、compile_diff 和 CPU/NPU
在内的完整硬件验收：

```bash
bash scripts/test.sh --hardware
```

硬件测试默认由 `unittest` 跳过，只有设置 `FORGEFUZZ_RUN_HARDWARE=1` 才执行，
所以普通开发机和 CI 不会因缺少 CANN/NPU 而误失败；`--hardware` 自动启用严格模式。
也可分别手工运行真实流程：

```bash
python main.py run --backend triton --seed 42 --device interpreter
python main.py run --backend triton --seed 42 --device npu --oracle-mode torch
python main.py run --backend ascendc --seed 42 --device npu --oracle-mode metamorphic
```

`runs/`、cache、编译产物和二进制均被 `.gitignore` 排除。

## 已知限制

- Triton NPU 运行依赖旧项目的固定 Python/Triton 环境。ForgeFuzz 自动选择 `.envs/triton-ascend/bin/python`，也可用 `triton_python` 覆盖；不会执行会向旧仓库创建 cache 的 `activate_env.sh`。
- AscendC 生成器覆盖范围很大，部分随机算子组合本身可能无法编译；这是应保留的 fuzz 结果，不会吞掉。默认 allowlist 选择基础算子以提供稳定 smoke path。
- AscendC 随机图没有普适的 CPU golden；因此默认使用旧项目真实的蜕变 variant。`golden` 模式必须由使用者确认 template golden 与 case 语义一致。
- `run_once.sh` 内部会重建项目自己的 `input/`/`output/`，但这些目录已被隔离到 case，不会写旧项目。
- 当前 campaign 是单进程顺序调度，没有 coverage 队列、并行 worker 或自动规约；这些不是统一执行协议正确性的前提。
