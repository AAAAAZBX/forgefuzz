# ForgeFuzz

ForgeFuzz 是一个面向计算图程序的轻量、反馈驱动 Fuzz 框架。核心代码不依赖具体语言：Triton、AscendC、PyTorch、CUDA 或其他 DSL 都通过适配器接入。

它借鉴了两个现有工程中已经验证过的通用设计：

- `triton-fuzzer-main` 的语义模型、生成/发射/执行分层、进程隔离、超时、失败指纹、语料包和覆盖反馈；
- `fuzz_code_generation` 的计算图驱动生成、算子约束、程序模板填充、变形测试、批量 campaign 和结果归档思路。

新项目没有直接复制语言相关实现。第一版把这些能力收敛成一个小而稳定的插件协议，便于后续逐个迁移语言适配器。

## 架构

```text
API/约束目录 ──> generate/mutate ──> 通用 Graph IR ──> adapter.emit
                                                        │
                                                        v
语料队列 <── novelty/失败指纹 <── adapter.observe <── compile/run
```

- `model.py`：可序列化的通用 Graph IR 和执行结果；
- `plugin.py`：新语言只需实现的 `LanguageAdapter`；
- `runner.py`：独立进程组、硬超时、日志捕获；
- `scheduler.py`：基于新特征与新失败的简化 AFL 风格反馈；
- `corpus.py`：测试用例、interesting queue 和失败归档；
- `engine.py`：语言无关 campaign 主循环；
- `adapters/python.py`：零依赖的参考适配器。

## 快速开始

不安装也可以从源码运行：

```bash
PYTHONPATH=src python -m forgefuzz run --iterations 10 --seed 1 --output runs/demo
```

开发安装：

```bash
python -m pip install -e '.[dev]'
forgefuzz run --iterations 10 --output runs/demo
pytest
```

每个 case 都会保留 `graph.json`、生成程序、编译/运行日志和 `result.json`。`corpus/queue` 保存产生新反馈的输入，`corpus/failures` 按失败指纹去重归档。

## 最小运行闭环

```text
生成 Graph → 执行并提取反馈 → interesting Graph 进入 corpus
     ↑                                  ↓
     └──── 从 corpus 选择并通过 GraphMutator 变异 ────┘
```

复现任意已保存 case：

```bash
PYTHONPATH=src python -m forgefuzz replay \
  runs/demo/cases/id_000000 --adapter python
```

第三方可以继承 `GraphMutator` 增加结构化变异；如果不提供，框架自动使用 Adapter 自带的 `mutate`。

## 当前范围

这是可运行的 MVP，不等同于完整 AFL++。当前反馈来自适配器提供的语义/结果特征；共享内存边覆盖、forkserver、确定性 mutation 阶段、崩溃最小化和多 worker 尚在路线图中。

## 为自己的语言生成独立项目

```bash
forgefuzz init my-language-fuzzer --adapter-name my_language
cd my-language-fuzzer
```

生成的不是片段，而是一套可独立安装、测试和发布的 adapter package，包含 API catalog、完整适配器、entry point、测试以及逐步替换说明。使用者不需要 fork 或修改 ForgeFuzz。

```bash
pip install -e .
forgefuzz adapters
forgefuzz run --adapter my_language --iterations 100 --output runs/first
```

完整操作手册见 [从零搭建测试体系](docs/USER_GUIDE.md)，接口细节见 [新语言接入指南](docs/ADDING_A_LANGUAGE.md)，后续建设计划见 [docs/ROADMAP.md](docs/ROADMAP.md)。

## PyTorch 样例

仓库包含一个 eager 与 `torch.compile` 差分测试样例：

```bash
PYTHONPATH=src python -m forgefuzz run \
  --adapter pytorch --iterations 10 --timeout 60 \
  --output runs/pytorch-demo
```

具体说明见 [examples/PYTORCH_EXAMPLE.md](examples/PYTORCH_EXAMPLE.md)。
