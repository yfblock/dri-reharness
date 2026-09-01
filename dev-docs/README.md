# reharness 开发文档

本目录是 `reharness` 项目的开发者和 Agent 交接资料。文档记录当前
`langgraph` 分支的真实入口、架构边界、验证证据、开发过程和已知风险。

文档日期：2026-08-26

当前工作分支：`langgraph`

## 先读什么

| 目的 | 文档 |
| --- | --- |
| 第一次运行项目 | [01-使用说明.md](01-使用说明.md) |
| 理解整个翻译和验证链路 | [02-系统架构.md](02-系统架构.md) |
| 了解本分支做过什么 | [03-开发记录.md](03-开发记录.md) |
| 接手任务前的 Agent 约束 | [04-Agent记忆.md](04-Agent记忆.md) |
| 遇到错误时排查 | [05-故障排查.md](05-故障排查.md) |
| 查看 LangGraph 三层拓扑 | [langgraph-topology.html](langgraph-topology.html)（主图 / generation 子图 / experiment 修复环，2026-08-30 与代码同步） |

## 项目定位

`reharness` 从 Linux C 设备驱动中提取结构化设备交互证据，生成 RIS、
DeviceSpec 和后端候选，并通过静态 contract、Kbuild、QEMU 和 manifest-owned
subsystem tests 做闭环验证。

当前主链路为：

```text
Linux C driver
    -> libclang extractor
    -> RIS / DeviceSpec / Facts / generation contract
    -> LangGraph orchestration
    -> LangChain OpenAI-compatible model (generation only)
    -> candidate Linux module
    -> Kbuild / AST / registration checks
    -> manifest-driven QEMU
    -> subsystem test evidence / unload
    -> accepted, failed, or inconclusive
```

每一层都保留自己的 evidence。下一层不能用“源码看起来像支持”替代上一层
缺失的结构化证据。

## 当前验证状态

截至 2026-08-25 的新鲜验证：

- 默认 profile matrix：9 个 required profile 全部 `accepted`。
- 通过的 profile：`amba-generic`、`i2c-generic`、`mdio-generic`、
  `network-generic`、`pci-generic`、`platform-generic`、`spi-generic`、
  `usb-generic`、`virtio-generic`。
- `serdev-generic` 已能识别和进入静态流程，但没有受信任的 runtime fixture，
  仍为 explicit-only / runtime-inconclusive，不属于默认验收集合。
- AMBA 代表性 fixture 已完成 resource registration、driver probe、sysfs
  subsystem test 和 candidate/registrar unload 闭环。
- focused Python tests：`77 passed`，覆盖 profile runtime、profile matrix 和
  driver profile registry。
- 验证产物：`artifacts/profile-matrix-final/matrix.json`。

这些结果证明的是 profile-owned、代表性的 framework contract，不是“整个 Linux
总线或子系统已经被完整测试”。任何报告、论文或 Agent 结论都必须保持这个范围。

## 权威参考

- 公共命令入口：[../run.sh](../run.sh)
- 用户级项目说明：[../README.md](../README.md)
- 确定性实验复现：[../REPRO.md](../REPRO.md)
- profile catalog：[../benchmarks/driver-profile-definitions.json](../benchmarks/driver-profile-definitions.json)
- subsystem provider catalog：[../benchmarks/subsystem-providers.json](../benchmarks/subsystem-providers.json)
- manifest loader：[../src/experiment_manifest.py](../src/experiment_manifest.py)
- profile registry：[../src/driver_profiles.py](../src/driver_profiles.py)
- LangGraph workflow：[../src/langgraph_workflow/](../src/langgraph_workflow/)
- LangChain bridge：[../src/langchain_bridge.py](../src/langchain_bridge.py)
- generic QEMU runner：[../scripts/qemu/qemu_run.sh](../scripts/qemu/qemu_run.sh)
- profile matrix runner：[../qa/verification/run_profile_matrix.py](../qa/verification/run_profile_matrix.py)

## 维护规则

开发文档不是独立的配置源。命令和 schema 发生变化时，先以代码、manifest
loader 和验证报告为准，再同步本目录。每次写入“已通过”“已支持”“完整验证”等
结论，都必须附带实际命令、时间和 artifact 路径。
