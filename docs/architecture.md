# Architecture

ForgeFuzz 的公共层只认识 case、阶段和结果，不认识 KernelSpec 节点或 AscendC 图节点。

## 生命周期

`CaseBundle.create` 先建立完整目录和解析后的配置。`run_pipeline` 依次调用 Backend；第一次失败后停止核心阶段，但总会运行公共 report。每个阶段先创建不可复用的 `attempt-NNN`，再原子更新 `case.json`。

创建 case 时还会写入 `configs/provenance.json`，记录两个上游 checkout 的绝对路径、Git commit、tracked dirty 状态、Python 平台、CANN 路径和 SoC。`stage`、`resume`、`replay` 和完整运行通过 case 级非阻塞文件锁避免并发写坏状态。

`stage`、`resume` 和 `replay` 都复用同一执行函数：

- stage：检查直接前置结果，追加一次 attempt；
- resume：移除指定点之后的“最新状态”，不删除历史 attempt；
- replay：创建新 CaseBundle，使用旧 seed/config，并比较原生表示 hash。

## 隔离

`ProcessRunner` 使用参数列表启动新进程组，禁用 core dump，分别重定向 stdout/stderr，并在 timeout 时先 TERM 后 KILL。显式环境覆盖写入命令清单。一个阶段包含多个子进程时共享同一个总 timeout budget，而不是每个子进程重新获得完整 timeout。

Triton 的 cache/dump/reproducer/bytecode 指向 case。AscendC 的 baremix、build、input、output 都在 case 内。旧项目只作为 Python/脚本/模板源读取。

## 状态与报告

`case.json` 是运行中的状态源，包含最新阶段结果与 attempt 索引。`report.json` 是面向消费方的最终快照，包含首个失败边界、全部核心结果、文件 SHA-256 清单和重放命令。manifest 排除 cache 和 CMake build/input/output 等可重建临时目录，避免报告阶段重复哈希大体积中间文件。
