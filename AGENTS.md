# Cairn Data Agent Repository Guide

本文件适用于整个仓库。

## 产品边界

- 本仓库是教学参考实现，不宣称具备生产级多租户、调度、审批或隔离能力。
- 核心层只能包含跨业务通用原语；业务术语、指标和示例进入 `scenarios/`、`knowledge/` 或 `skills/`。
- 模型只能返回类型化计划或澄清，不能直接访问 shell、宿主文件系统、数据库或任意网络。
- 计算由白名单执行器完成，回答必须引用已持久化的 Artifact。
- 外部写入不在教学版支持范围内。

## 工程约束

- Python 使用 Ruff、mypy、pytest；TypeScript 使用 TypeScript、Prettier、Vitest。
- 新功能和缺陷修复都需要测试。
- 示例必须使用合成数据，不得提交凭证、个人信息、生产数据或运行时产物。
- 修改契约时同步更新文档、示例和契约测试。
- 提交前运行 `./scripts/check.sh`。

## 完成定义

- 离线模式不需要 API Key 或网络。
- 至少一个表格场景和一个文档场景能完成数据到证据回答的闭环。
- 新增 Scenario 不需要修改核心源码。
