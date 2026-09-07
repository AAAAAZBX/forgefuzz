# ForgeFuzz 完整项目介绍

## 1. 项目目标

ForgeFuzz 是一个以计算图为统一中间表示的通用代码测试系统。被测对象可以是 NumPy、PyTorch，也可以是 Triton、AscendC、CUDA 或新的编译器 DSL。框架复用同一条测试流水线，语言差异全部收敛到 Adapter：算子约束、源码模板、构建命令、运行环境、等价规则和数值 Oracle。

它不是随机拼接源码的脚本，而是一个可复现、可扩展、可归档的测试闭环：

```text
结构化 API catalog
        |
        v
约束驱动 Graph 生成 <---- interesting corpus
        |                         ^
        v                         |
节点/属性/拓扑变异                | 反馈调度
        |                         |
        v                         |
base Graph ---- 等价变换 ---- variants
        |                         |
        +------ Adapter.emit -----+
                    |
                    v
             独立可运行项目
                    |
                    v
           compile / run / timeout
                    |
                    v
       differential / metamorphic Oracle
                    |
                    v
       特征提取、失败去重、完整归档
```

## 2. 对两个参考工程的吸收

AscendC 工程贡献了主流程的形态：从算子池生成计算图，在主路径和分支中插入算子，把图填入一套完整工程模板，生成基线工程和代数等价工程，随后进行批量编译、真机执行和容差比较。ForgeFuzz 保留这些阶段，但把 AscendC wrapper、CMake、NPU 命令和具体规则移入 AscendC Adapter。

Triton 工程贡献了更严格的工程化机制：typed spec、生成/emit/execute 分层、base/variants case bundle、变换记录、输入 manifest、进程隔离与超时、覆盖反馈、失败归档及 reducer 接口。ForgeFuzz 将其中与语言无关的部分放入核心协议，同时保持一个小型实现，避免核心依赖 Triton 或硬件 SDK。

## 3. 核心对象

| 对象 | 职责 | 是否语言相关 |
|---|---|---|
| `TensorType` | dtype 与 shape | 否 |
| `Node` | 算子、输入边、输出类型和属性 | 否 |
| `Graph` | 拓扑有序 DAG、输入、输出和元数据 | 否 |
| `OpSpec` | 算子 arity、dtype、rank、属性候选 | 数据由 Adapter 提供 |
| `MetamorphicVariant` | 变体图、关系名和变换证据 | 协议通用，规则语言相关 |
| `ProgramArtifact` | 入口文件、文件集、编译/运行命令和环境 | 协议通用，内容语言相关 |
| `ExecutionResult` | success/invalid/compile/runtime/timeout/mismatch 分类 | 否 |
| `Campaign` | 生成、变异、执行、调度、归档闭环 | 否 |

## 4. 一次 Campaign 如何运行

1. 使用固定 campaign seed 创建 Adapter 和随机数流。
2. 从空白生成新图，或从 corpus 选择旧图并变异。
3. `validate` 在调用昂贵工具链前过滤非法图。
4. `emit` 在 `base/program` 生成完整、独立可运行的项目。
5. 核心执行可选编译命令和运行命令，统一处理日志与硬超时。
6. Adapter 的普通 Oracle 判定参考实现差分或输出不变量。
7. Adapter 生成零到多个 `MetamorphicVariant`；每个变体写入独立目录并保存 `transform.json`。
8. 变体使用同一输入 seed 编译运行，metamorphic Oracle 比较 base/variant。
9. `observe` 返回 API、深度、结果类型、编译 pass 或覆盖边等特征。
10. 新特征或新失败指纹使 Graph 进入 corpus；失败按稳定 fingerprint 去重。

## 5. 当前可运行后端

- `python`：无第三方依赖的最小协议样例。
- `numpy`：3–8 节点随机 DAG、独立源码生成、交换律变体及 `allclose` Oracle，是接入其他框架的首选参考。
- `pytorch`：eager 与 `torch.compile` 差分 Oracle，可通过环境变量切换 backend。

NumPy 示例：

```powershell
$env:PYTHONPATH="src"
python -m forgefuzz run --adapter numpy --iterations 20 --seed 7 `
  --metamorphic-variants 1 --output runs/numpy
```

输出结构：

```text
runs/numpy/
├── cases/id_000000/
│   ├── graph.json
│   ├── base/program/case.py
│   ├── base/logs/run.log
│   ├── variants/commute_n2/
│   │   ├── graph.json
│   │   ├── transform.json
│   │   ├── program/case.py
│   │   └── logs/run.log
│   └── result.json
├── corpus/queue/
├── corpus/failures/
└── summary.json
```

## 6. 如何接入新语言

运行 `forgefuzz init my-fuzzer --adapter-name my_language` 创建独立 Adapter 包，然后完成六类资产：结构化 API catalog、合法 Graph 生成、结构化 mutation、静态验证、完整项目 emitter、Oracle/反馈。若语言支持等价变换，再实现 `metamorphic_variants` 与 `metamorphic_oracle`。

仓库中的 `.codex/skills/add-forgefuzz-adapter/SKILL.md` 是给另一个 Codex agent 的执行说明。把目标语言代码库和工具链路径告诉 agent，并要求使用该 skill，它会按统一契约完成实现与验收。

## 7. 推荐的 AscendC 与 Triton 迁移方式

AscendC Adapter 应直接消费现有 operator set、wrapper 和工程模板；`emit` 将 base/variant Graph 分别填入项目，返回 CMake/构建和 NPU 执行命令。现有代数规则应逐条转成带前置条件的 `MetamorphicVariant`，现有 tolerance JSON 转成按 dtype/op/规则选择的 Oracle 配置。

Triton Adapter 应复用 typed catalog、shape/dtype constraint 和 kernel emitter；输入 `.npy` 与 launch 参数应写入生成项目。Triton IR/coverage 信息通过 `observe` 暴露，已有 transform rules 映射为变体，已有 reducer 后续可实现为核心 reducer 插件。

两者都不应把 SDK import、硬件环境变量或编译器命令放进核心包。

## 8. 完成度与后续工作

当前版本已经完成单机顺序执行的完整功能闭环，以及 NumPy 的真实蜕变测试证明。下一阶段的优先级是：可校验输入 manifest 与环境快照、更多通用图 mutation、断点续跑、多 worker、稀有路径能量调度、失败自动最小化、原生 edge coverage，以及正式迁移 Triton/AscendC Adapter。硬件 Adapter 的最终验证必须在对应 SDK 和设备环境中完成。
