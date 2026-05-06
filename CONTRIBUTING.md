# 参与贡献

感谢你帮助 Cairn Data Agent 变得更清晰、更可靠。这个仓库的首要目标是教授一条可验证的 Data Agent 主链路，因此贡献的价值主要来自边界清楚、实现真实和读者能够复现，而不是功能数量。

## 开始之前

请先阅读：

- [README](README.md)：项目定位、运行方式和安全边界；
- [Service 主链路](src/cairn_data_agent/service.py)：提问与证据回答；
- [Scenario 示例](scenarios/travel-budget/scenario.yaml)：业务配置的放置方式；
- [仓库协作约定](AGENTS.md)：适用于整个仓库的工程要求。

本项目以 [MIT License](LICENSE) 发布。提交贡献即表示你确认有权提交相关内容，并同意该贡献按 MIT License 发布。引入第三方代码、数据或素材前，必须确认其许可证与本项目兼容，并保留依法需要的版权和许可声明。

## 本地环境

需要 Python 3.12、uv、Node.js 24 和 npm。

```bash
uv sync
npm ci --prefix web
./scripts/demo.sh
./scripts/check.sh
```

启动后端和 Web 开发服务器：

```bash
./scripts/dev-up
```

默认使用完全离线的 fake model。开发和测试不应依赖网络、真实模型、生产数据库或 API Key。

## 应该把改动放在哪里

| 需求 | 首选位置 |
| --- | --- |
| 术语、字段含义、指标公式、回答注意事项 | `scenarios/<name>/knowledge/` |
| 一组领域说明、知识、示例问题和评测 | `scenarios/<name>/` |
| 独立的只读或纯计算扩展契约 | `skills/<name>/` |
| 两个以上结构不同场景都需要的通用数据原语或安全不变量 | `src/cairn_data_agent/` |
| 学习工作台展示与交互 | `web/` |

不要因为一个场景需要某个字段或指标，就在核心中增加业务名称、字段判断或专用 step kind。新增 Scenario 应当不修改核心 Python / TypeScript 源码；可参照 [travel-budget 场景](scenarios/travel-budget/scenario.yaml)及其示例和评测文件。

## 开发约束

- 模型只能输出 `DataPlan` 或 `Clarification`，不能获得 shell、任意文件、数据库或任意网络访问；
- 执行器只接受通过完整 Policy 校验的计划，只运行显式白名单操作；Skill 必须来自发行包内置资源或操作者显式配置并审查过的本地目录，由 Scenario 授权并通过 Registry 校验；
- 外部写入不在教学版支持范围内；
- Answer 必须引用本次 Run 已持久化的 Artifact；
- 示例、fixture 和文档输出必须是合成数据，不得含凭证、个人信息或生产数据；
- 不提交 `.env`、`runtime-data/`、SQLite 文件、Blob、日志、缓存、覆盖率产物、`node_modules/` 或 `web/dist/`；
- API Key 只通过环境变量注入，不写入日志、测试快照或文档示例；
- 程序不会自动加载当前目录的 `.env`；需要本地配置时由 shell、容器或进程管理器显式注入 `CAIRN_*` 环境变量；
- 不提交内部路径、内部域名或只在个人机器上成立的命令。

Python 使用 Ruff、mypy strict 与 pytest；TypeScript 使用 TypeScript、Prettier 与 Vitest。尽量保持函数和数据契约小而明确，避免只为“未来可能使用”创建空接口。

## 测试要求

每个新功能或缺陷修复都需要覆盖对应行为，测试层次按改动选择：

- Contract：合法对象可解析，未知字段、版本和 step kind 被拒绝；
- Policy：资产越权、错误引用、重复 Step 或环形依赖被拒绝；
- Executor：同一输入和 Plan 得到内容等价结果；
- Artifact：摘要、Run / Step 关联和 lineage 完整；
- Scenario：新包可由 Registry 自动发现，离线示例可绑定合成资产；
- Skill：manifest/schema 拒绝非法 effect 或权限，Plan allowlist 不能绕过，受信 handler 的输入输出符合 schema 和大小限制；
- API / 主链路：上传、提问、执行、Artifact 和证据回答闭环；
- Web：关键状态渲染、API 适配和构建。

修改版本化 contract 时，必须同步更新：

1. Pydantic 类型和策略校验；
2. 执行器或模型适配器；
3. Scenario 示例计划与评测；
4. 前端类型与展示；
5. 契约测试和相关文档。

## 提交前检查

运行统一入口：

```bash
./scripts/check.sh
```

它会检查 Python lint、格式、类型、测试覆盖率，执行仓库敏感信息检查，检查、测试和构建 Web；还会离线构建 sdist/wheel，把全量成员与 Git 跟踪清单、制品内容与当前构建工作树逐项核对，在临时环境安装后从空目录跑完整 Scenario Demo。新增文件需先进入 Git 暂存区，才能成为可审计的候选制品。修复根因，不要通过放宽类型、删除断言、降低覆盖率或跳过安全检查让流水线变绿。

若需定位问题，可分别运行：

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest
npm run check --prefix web
npm run test --prefix web -- --run
npm run build --prefix web
```

## 变更说明

一个容易审查的变更应说明：

- 要解决的学习或工程问题；
- 为什么属于 Core、Scenario、Knowledge 或 Skill；
- 哪些安全不变量可能受影响；
- 实际运行了哪些测试及结果；
- 是否更改 contract、示例数据、依赖或对外行为；
- 尚未验证的部分及原因。

保持改动聚焦，不混入无关格式化或重构。依赖升级应说明必要性，并确认来源、许可证和离线测试影响。

## Scenario 贡献检查表

- [ ] 目录名与 `metadata.name` 一致，版本清楚；
- [ ] 只声明实际支持的 CSV、XLSX 或 Markdown 类型；
- [ ] 领域内容全部位于 Scenario / Knowledge / Skill；
- [ ] `examples.yaml` 只使用通用 Plan step，并能在 fake 模式匹配；
- [ ] `evals.yaml` 引用合成 fixture，包含证据要求；
- [ ] 没有把外部写入或自由网络权限带入教学版；
- [ ] executable Skill 仅包含经过审查的发行包内置或显式本地纯函数，并明确同进程执行不是沙箱；
- [ ] 新增场景无需修改核心源码；
- [ ] 文档和 `./scripts/check.sh` 均已验证。

## 安全问题

不要在公开 Issue、日志或测试 fixture 中粘贴真实密钥、个人数据、内部地址或可利用细节。如果仓库托管平台已配置私密安全报告入口，请优先使用；否则先通过维护者提供的私密联系方式请求报告渠道。当前教学版没有生产级安全承诺，发现越权访问、路径逃逸、凭证泄漏或任意代码执行风险时，应停止使用受影响功能并明确标注未验证范围。
