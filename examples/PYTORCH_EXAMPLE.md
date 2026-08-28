# PyTorch 样例

这个样例演示如何用 ForgeFuzz 建立一条完整但精简的真实框架测试链路：

```text
生成三节点 Graph → 生成 PyTorch 程序 → eager 参考执行
                                      → torch.compile 目标执行
                                      → 比较输出 → 收集反馈
```

适配器源码位于 `src/forgefuzz/adapters/pytorch.py`。

## 1. 准备环境

要求 Python 3.10+、PyTorch 2.1+：

```bash
python -m pip install -e '.[pytorch]'
```

如果环境已经安装 PyTorch，可直接从源码运行。

## 2. 运行样例

```bash
PYTHONPATH=src python -m forgefuzz run \
  --adapter pytorch \
  --iterations 10 \
  --seed 1 \
  --timeout 60 \
  --output runs/pytorch-demo
```

默认使用 `torch.compile(..., backend="eager")`，适合快速验证整条链路。测试 Inductor 时执行：

```bash
FORGEFUZZ_TORCH_BACKEND=inductor \
PYTHONPATH=src python -m forgefuzz run \
  --adapter pytorch --iterations 10 --timeout 180 \
  --output runs/pytorch-inductor
```

## 3. 查看结果

```text
runs/pytorch-demo/
├── cases/id_000000/
│   ├── graph.json
│   ├── program/case.py
│   ├── logs/run.log
│   └── result.json
├── corpus/queue/
├── corpus/failures/
└── summary.json
```

`program/case.py` 是完整的独立复现程序，可以直接运行：

```bash
python runs/pytorch-demo/cases/id_000000/program/case.py
```

也可以通过框架重新执行保存的 Graph：

```bash
PYTHONPATH=src python -m forgefuzz replay \
  runs/pytorch-demo/cases/id_000000 --adapter pytorch --timeout 60
```

## 4. 样例包含的扩展点

- `generate`：生成 `binary → unary → binary` 三节点图；
- `mutate`：保持输入数量合法并替换算子；
- `validate`：检查算子、参数数量和数据依赖；
- `emit`：生成 eager 与 compiled 两条执行路径；
- `oracle`：以 `max_abs_diff <= 1e-5` 判断结果；
- `observe`：记录覆盖到的算子、后端和结果类型。

## 5. 扩展成自己的 PyTorch 测试体系

按下面四步推进即可：

1. 扩充算子及 shape/dtype 约束；
2. 增加拓扑、属性和输入值变异；
3. 按 dtype/op 配置比较容差；
4. 增加 CUDA、Inductor 或其他后端的 CI campaign。
