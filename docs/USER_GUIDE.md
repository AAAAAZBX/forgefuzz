# 从零搭建自己的 Fuzz 测试体系

本文面向第一次接触 ForgeFuzz 的使用者。目标不是运行仓库内置 demo，而是建立一个独立、可交付给团队使用的语言测试项目。

## 最终会得到什么

完成后会有两个互相独立的包：

- `forgefuzz`：稳定的 campaign、执行、反馈和语料基础设施；
- `your-language-fuzzer`：你维护的 API 规则、图生成器、代码生成器、Oracle 和环境配置。

升级核心框架不要求把语言代码合并进 ForgeFuzz，语言项目也可以单独建仓、测试和发布。

## 第一步：生成项目

```bash
python -m pip install -e /path/to/forgefuzz
forgefuzz init mydsl-fuzzer --adapter-name mydsl
cd mydsl-fuzzer
python -m pip install -e '.[dev]'
```

生成目录如下：

```text
mydsl-fuzzer/
├── pyproject.toml                 # 安装信息和 adapter entry point
├── README.md                      # 本项目的运行与改造说明
├── src/mydsl_fuzzer/
│   ├── api_catalog.json           # API 及约束的唯一数据源
│   └── adapter.py                 # 五阶段实现
└── tests/test_adapter.py          # 最低限度契约测试
```

先不要修改任何代码，验证脚手架：

```bash
forgefuzz adapters
forgefuzz run --adapter mydsl --iterations 10 --seed 1 --output runs/smoke
```

## 第二步：整理语言资产

不要从代码模板开始。先收集并结构化以下信息：

| 资产 | 必需内容 | 用途 |
|---|---|---|
| API catalog | 名称、参数、返回值、属性 | 选择节点和填充接口 |
| 类型规则 | dtype、shape、rank、layout | 生成合法边和输入 |
| 前置条件 | 值域、对齐、广播、内存空间 | 静态过滤 |
| 工具链 | 生成、编译、运行命令 | 构造 `ProgramArtifact` |
| Oracle | 参考实现、等价关系或不变量 | 判断静默错误 |
| 反馈源 | 覆盖、IR pass、API 组合、错误类型 | 保留 interesting corpus |

建议先录入 3–5 个简单 API 跑通闭环，再扩大目录。一次录入全部 API 很难定位规则错误。

## 第三步：替换适配器的五个阶段

### `generate`

从 catalog 选择 API，利用类型和前置条件生成合法 `Graph`。所有随机选择必须使用传入的 `rng`，否则同一 seed 无法复现。

### `mutate`

至少实现一种 mutation，逐步增加：替换 op、修改属性、插入/删除节点、改变拓扑、dtype/shape mutation、特殊输入值。变异后仍应满足静态约束，或由 `validate` 快速拒绝。

### `validate`

检查引用、拓扑、arity、类型、shape、属性和硬件约束。这里的失败属于无效输入，不应算作编译器 bug。

### `emit`

在 case 的 `program/` 下生成完整项目，并返回：

```python
ProgramArtifact(
    entrypoint=source_file,
    files=(source_file, config_file),
    compile_command=("compiler", "..."),  # 解释执行语言可为 None
    run_command=("runtime", "..."),
    environment={"CACHE_DIR": "..."},
)
```

不要在 `emit` 中调用编译器。ForgeFuzz 统一负责隔离、超时、日志和分类。生成目录必须能脱离框架手工重放。

### `oracle` 与 `observe`

`oracle` 把“进程成功但结果错误”改判为 `OUTPUT_MISMATCH`。`observe` 只负责返回特征，例如 `api:add`、`ir:vectorize`、`edge:1234`；新特征会使 case 进入 queue。

## 第四步：建立测试金字塔

提交 adapter 前至少建立：

```text
快速、每次提交：catalog schema / constraint / deterministic / emitter snapshot
编译环境：固定 seed 的 generate -> compile smoke
设备环境：固定已知 case + 小型 campaign
夜间任务：长 campaign、语料合并、失败复现与 reduction
```

必须故意注入一个错误，确认 Oracle 能报出 mismatch；必须制造死循环，确认 timeout 后没有残留子进程；必须重复同一 seed，确认源码和输入一致。

## 第五步：部署 campaign

为真实测试环境锁定并记录：

- adapter 和编译器 commit；
- SDK、driver、runtime、设备型号；
- Python 和依赖版本；
- ForgeFuzz seed、timeout 和迭代数；
- 环境变量白名单。

CI 中先运行环境自检和固定 smoke case，再运行 fuzz。否则 SDK 缺失、设备掉线等问题会污染失败统计。

## 如何阅读输出

```text
runs/demo/
├── cases/id_000000/       # graph、生成程序、日志、结果
├── corpus/queue/          # 触发新反馈的 graph
├── corpus/failures/       # 按失败指纹去重的失败
└── summary.json           # campaign 汇总
```

处理失败时，先进入对应 case 的 `program/` 手工执行编译和运行命令。确认可复现后，再归类为工具链错误、环境错误、无效 case 或真实缺陷。

## 何时算完成第一套体系

- 新成员只看项目 README 就能安装并运行；
- 无需修改 ForgeFuzz 源码；
- API 约束有结构化来源；
- 每个失败都包含可重放程序和日志；
- 相同 seed 可复现；
- Oracle 能发现至少一个静默错误；
- CI 和真机 campaign 都有明确命令；
- 环境故障不会被记作产品 bug。
