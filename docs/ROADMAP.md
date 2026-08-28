# 后续方案

## Phase 1：通用 MVP（当前）

- 通用 Graph IR 与插件协议；
- 约束驱动生成/变异接口；
- 编译、运行隔离与超时；
- 特征新颖度、失败指纹和语料归档；
- 零依赖 Python 端到端样例。

## Phase 2：可用于真实语言

- 增加输入数据模型与可复现的 tensor/blob 存储；
- Oracle 插件协议和 differential/metamorphic 内置实现；
- 通用拓扑、节点、属性、shape/dtype mutation 库；
- case manifest、文件哈希、环境快照和 `replay` 命令；
- PyTorch、Triton、AscendC 三个独立适配器；
- campaign 状态持久化、断点续跑和并行 worker。

## Phase 3：接近简配 AFL++

- 语料能量调度与稀有路径加权；
- 确定性 mutation、havoc 和 splice 阶段；
- 编译器/运行时原生覆盖采集，支持 edge bitmap；
- forkserver 或常驻 worker，降低启动开销；
- crash 去重、自动 graph/program reduction；
- hang 队列、资源上限、设备健康恢复；
- corpus import/export、跨机器同步和统计面板。

## 从参考工程迁移的原则

- 搬协议和机制，不搬语言常量；
- 通用核心禁止 import Triton、torch、CANN；
- 环境变量、编译命令和 artifact 约定归适配器；
- 变形规则以 IR-to-IR transform 插件表达；
- 所有真实失败必须保存可重放程序、输入、环境和 oracle 证据。
