# 随机计算图生成

ForgeFuzz 的随机组合图位于 `src/forgefuzz/generate.py`，核心只有两个对象：

- `OpSpec`：描述算子名称、输入数量、dtype、rank 和属性候选；
- `RandomGraphGenerator`：根据算子规格生成无环、多节点且全部存活的 Graph。

## 生成方法

```text
输入值池
  ↓
选择兼容算子
  ↓
强制连接上一个节点，形成主链
  ↓
从输入或旧节点随机选择其余操作数
  ↓
形成分支/汇合边
  ↓
最后一个节点作为 Graph 输出
```

主链保证每个节点都能影响最终输出；其余随机输入边产生不同拓扑，同时不会产生前向引用或环。

## 最小示例

```python
import random

from forgefuzz import OpSpec, RandomGraphGenerator, TensorType

ops = (
    OpSpec("add", 2, dtypes=("float32",), ranks=(2,)),
    OpSpec("mul", 2, dtypes=("float32",), ranks=(2,)),
    OpSpec("relu", 1, dtypes=("float32",), ranks=(2,)),
)

tensor = TensorType("float32", (4, 4))
graph = RandomGraphGenerator(ops, min_nodes=3, max_nodes=8).generate(
    random.Random(1), {"x": tensor, "y": tensor}
)
```

相同 seed 会得到完全相同的 Graph；不同 seed 会改变节点数量、算子组合和连接关系。

## 与参考项目的关系

- 借鉴 Triton 项目的确定性 DAG、算子 arity、主链存活性和随机回连；
- 借鉴 AscendC 项目的算子池、按输入数量选择以及主路径加随机分支；
- 没有迁移语言名称、硬件约束、控制流和代码模板，它们仍由 Adapter 提供。
