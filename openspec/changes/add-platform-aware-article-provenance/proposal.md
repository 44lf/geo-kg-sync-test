## Why

当前 GEO 文章生成链路只在模板目录和最终发布阶段局部感知平台，目标平台没有贯穿目标解析、写作、保存、审核和发布校验；文章虽然记录模板 ID/名称，却无法在模板修改后还原当时实际使用的模板正文、最终提示词和平台规则。结果是平台错配可能延迟到发布阶段才暴露，历史文章也无法可靠复盘生成依据。

## What Changes

- 为文章增加可检索的目标内容平台，历史文章保持“未记录”，不做推测性回填。
- 将目标平台贯穿 Pipeline/MCP 生成、模板选择、Writer、Verifier、文章保存和发布任务创建。
- 在服务端保存边界强制校验模板用途及模板平台兼容性，发布边界默认拒绝目标平台错配。
- 为每篇新生成文章保存一份不可变的生成上下文快照，包括模板正文、最终有效提示词及哈希、平台规则版本/快照、问题来源、模型与生成参数。
- 扩展 GEO MCP 文章工具契约，使生成端能够提交平台和生成上下文，读取端能够查询精简或完整溯源信息，并按平台隔离当日循环文章。
- 同步更新 geo-goal Orchestrator、Writer、Verifier，使其使用同一目标平台和平台规则版本；Verifier 不再忽略平台维度。
- 保持旧 MCP 调用和历史文章可读；新 `/goal` 生成链路必须提交平台与所需溯源字段。

## Capabilities

### New Capabilities

- `platform-aware-article-generation`: 规定目标平台如何贯穿生成、模板兼容校验、审核和发布防错链路。
- `article-generation-provenance`: 规定文章生成上下文的不可变快照、MCP 读写契约、历史兼容和敏感信息约束。

### Modified Capabilities

无。当前仓库没有已建立的主规格目录，本变更新增上述能力规格。

## Impact

- 数据库：`articles` 增加可空、可索引的目标平台字段；新增文章生成上下文一对一表。迁移必须等待当前采集器迁移稳定后，从实施时真实 Alembic head 生成，不预占 revision 编号。
- 后端：文章模型/Schema/Service、MCP Article 路由与工具、模板运行时选择、Pipeline 生成节点、发布任务创建校验及测试。
- MCP：`save_article`、`get_article`、文章列表/当日循环查询和模板/平台策略读取契约。
- Skill：`E:\geo-claude-plugins` 中 geo-goal Orchestrator、Writer、Verifier 及插件版本清单；发布时遵循该仓库的 Git → DB 正式同步流程。
- 兼容性：旧文章的平台和生成上下文可为空；旧客户端暂时可省略新增参数，但新 geo-goal 链路必须提供。
- 安全与存储：提示词快照不得保存 Token、密钥或授权头，需限制尺寸并生成内容哈希。
