# Versioned contracts

`src/cairn_data_agent/contracts.py` 是运行时契约的单一事实来源；本目录保存供 Web、Scenario 作者和
其他语言客户端使用的公开 JSON Schema。更改契约时必须同时更新 schema、示例计划与契约测试。

- `data-plan.v1.schema.json`：模型可提交的白名单数据计划；
- `clarification.v1.schema.json`：证据不足时返回的结构化澄清。

未知字段默认拒绝。Schema 通过 Draft 2020-12 校验，Scenario 中的离线计划同时经过 JSON Schema 和
Pydantic 校验，以防公开制品与运行时发生漂移。

契约测试还会把覆盖全部 Step 类型的 Pydantic `model_dump(mode="json")` 结果交给公开 Schema
复验，包括 `derive` 二选一操作数序列化时出现的另一侧 `null`，以及各 Step 的默认字段。
