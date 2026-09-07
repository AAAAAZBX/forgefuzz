# 接入新语言或框架

内置后端放在 `src/forgefuzz/adapters/<name>/`；团队自己的后端建议用 `forgefuzz init` 创建独立包。它需要实现 `LanguageAdapter` 的基础阶段，并按需实现蜕变阶段。

## 1. 建立 API 与约束目录

需要准备：

- 算子名称、输入/输出个数和属性；
- dtype、shape、layout、memory space 等类型规则；
- 前置条件、硬件限制、合法值域和副作用；
- 可用于反馈的 API、IR pass、代码路径或运行时特征。

目录应是结构化数据或 Python schema，不要把规则散落在代码模板中。AscendC 可先转换 `ops/` 和 wrapper 信息；Triton 可转换现有 catalog/spec。

## 2. 实现适配器

```python
class MyAdapter(LanguageAdapter):
    name = "my_language"

    def generate(self, rng): ...       # 约束驱动生成 Graph
    def mutate(self, graph, rng): ...  # 图/属性/输入值变异
    def validate(self, graph): ...     # 静态合法性检查
    def emit(self, graph, out): ...    # 模板填充，返回 ProgramArtifact
    def observe(self, artifact, result): ...  # 提取覆盖/新颖度
    def metamorphic_variants(self, graph, rng): ... # 生成等价变体
    def metamorphic_oracle(self, base_artifact, base_result,
                           variant, variant_artifact, variant_result): ...
```

`emit` 产生的程序必须可脱离 ForgeFuzz 单独重放。编译和运行所需命令放进 `ProgramArtifact`，不要在适配器中自行启动子进程。

每个 `MetamorphicVariant` 必须声明稳定 id、关系名、变体 Graph 和变换证据。变体必须复用基线输入 seed；交换律、结合律等规则要先检查 dtype、溢出、NaN 和浮点精度前置条件。

## 3. 搭建测试环境

至少需要三层环境：

1. CPU 单元测试：catalog、约束、图验证、确定性生成和代码快照；
2. 编译 smoke test：少量固定 seed 能完成代码生成和编译；
3. 真机 campaign：GPU/NPU/目标 runtime，固定驱动、编译器和设备版本，并记录环境元数据。

建议提供容器镜像或锁定文件，以及 `doctor` 脚本检查编译器、SDK、设备节点和最小程序，避免把环境故障误报成语言 bug。

## 4. 定义 Oracle

按语言选择一项或多项：

- differential：与 NumPy、PyTorch eager、CPU 或另一后端比较；
- metamorphic：原图与等价变换图比较；
- crash/hang：非零退出、信号或超时；
- sanitizer/compiler verifier：解析诊断信息；
- invariant：shape、范围、单调性、NaN/Inf 等性质。

数值比较必须按 dtype/op 配置 `atol`、`rtol`、ULP 和 NaN 策略，不能使用一个全局阈值。

## 5. 必需验收项

- 相同 seed 生成完全一致的 graph 和程序；
- 非法 graph 在编译前被识别；
- compile failure、runtime failure、timeout、mismatch 被正确分类；
- case 目录可独立重放；
- 相同失败被稳定指纹去重；
- 至少一个故意注入的错误能被 oracle 捕获；
- 连续 campaign 不泄漏进程、缓存或设备资源。

## 推荐迁移顺序

1. PyTorch：环境简单，可作为通用图 IR 和 differential oracle 的验证后端；
2. Triton：复用现有 catalog、typed generator、emitter 和 IR coverage；
3. AscendC：把现有 graph/wrapper/模板与 metamorphic 规则逐步封装成适配器；
4. CUDA/其他 DSL：验证插件接口没有绑定既有语言假设。
