# Backend integration notes

## Triton

generate/emit 在 ForgeFuzz 进程内导入 `triton_ascend_fuzz`，同时禁止 bytecode，避免写旧项目。执行阶段使用旧项目的 Python 3.11 环境与 `third_party/triton-ascend/python`，但所有 cache 和 IR dump 重定向到 case。

emitter 生成的 harness 原生支持 `compile`、`run`、`interpreter`，并保存 Torch reference、NPU/interpreter NumPy 输出。因此适配器不重写 kernel launch 或 Torch reference 逻辑。

## AscendC

generate 直接调用旧 CLI。emit 捕获 `execute_graph.py` stdout 为 C++，再调用旧 `split_cpp_sections.py` 将代码注入 case 私有 baremix 模板。

旧生成器会遍历 Python 集合；仅设置图随机 seed 仍可能受进程 hash 随机化影响。适配器对所有 AscendC 子进程固定 `PYTHONHASHSEED=0`，自动测试验证同 seed/config 的 `graph.json` hash 一致。

旧模板的生成代码无条件引用 `../ops/mmad.h`，所以适配器物化旧 `ops/` 中三个普通文件，但显式排除其历史自指 `ops` 符号链接。该选择是构建依赖，不是复制旧仓库。

build/run 使用已经拆开的 `compile.sh` 与 `run_once.sh`。蜕变、CPU/NPU 和编译选项差分各自使用独立工程目录，避免共享 build/input/output。

`external` oracle 会在 emit 阶段把参考二进制复制到 case 的 `inputs/`，并记录来源、大小和 SHA-256；后续 oracle 不再依赖原始外部文件仍然存在。当前二进制 oracle 只支持 float32，因此配置层拒绝其他 `ascend_data_dtype`，避免静默误解析。
