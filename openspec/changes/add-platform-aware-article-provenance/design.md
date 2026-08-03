## Context

GEO 当前已经具备三个彼此分离的事实：

- `PromptTemplate.platform` 能区分 `xiaohongshu`、`toutiao`、`wechat_mp` 与通用模板；
- MCP 模板目录可以按平台筛选；
- `PublishTask`/`PublishRecord` 在文章生成之后记录实际发布平台。

但 `Article`、MCP `save_article`、Pipeline 写作节点以及 geo-goal Writer/Verifier 没有共同的平台契约。文章只保存模板 ID/名称和部分问题来源，模型标签还混在发布指标使用的 `Article.metrics` 中。模板或 Skill 后续修改后，无法还原当时的应用提示词和平台规则。当前 Toutiao 驱动还会在发布时静默截断标题，说明已知硬约束没有在生成/审核边界统一执行。

本变更跨越 `E:\geo` 后端、MCP、Pipeline 和 `E:\geo-claude-plugins` Skill。与此同时，另一个窗口正在实施采集器变更并持有未提交的 `0073_collector_gateway_models.py`，因此本变更在规划阶段不指定新 revision 编号，实施时必须从真实 Alembic head 接续。

2026-07-29 apply 预检记录：首次检查时 `alembic heads` 显示
`0073_collector_gateway_model`，对应文件仍未跟踪，所以当时没有抢占后继编号。待 collector 的迁移
实现、迁移测试和集中验证任务完成，且文件持续稳定后，再次确认单一真实 head，最终新增
`0074_article_platform_context` 并明确以 `0073_collector_gateway_model` 为父 revision。
`E:\geo` 的重叠风险集中在 `server/app/main.py`、`server/alembic/env.py`、`web/src/types.ts`、
`web/src/features/pipelines/PipelineEditor.tsx` 等采集器/前端在途文件；实现基于当时内容做最小补丁，
没有修改 collector revision。插件仓库先快进同步到当时 `origin/main`，保留了文档、压缩包和指针
文件等用户脏改；双 manifest 从上游 `1.5.3` 准备升级为 `1.5.4`。

## Goals / Non-Goals

**Goals:**

- 让一个明确的内容目标平台贯穿模板选择、写作、保存、审核和发布校验。
- 让新 geo-goal 文章可查询平台，并能复盘当时应用控制范围内的模板、最终提示词、平台规则、问题、模型和证据。
- 在服务端边界强制执行模板兼容和平台硬约束，避免 Skill 或直接模板 ID 调用绕过。
- 向后兼容历史文章、现有通用 Pipeline 和旧 MCP 客户端。
- 用紧凑列表响应与显式完整详情避免把大段提示词带入日常 MCP 上下文。

**Non-Goals:**

- 本次不引入 `ArticleVariant`，不实现一篇母稿自动派生多平台版本。
- 本次不改变发布效果指标当前的存储模型；按 `PublishRecord` 归因属于后续能力。
- 本次不建立可运营后台编辑的平台政策数据库；首期政策使用代码内版本化注册表。
- 本次不声称记录模型提供商隐藏的 system prompt、宿主应用开发者指令或完整对话，只记录 GEO 应用实际组装且可观察的有效提示词。
- 本次不对历史文章猜测回填平台、模板正文或生成提示词。

## Decisions

### 1. Article 保存查询热字段，独立表保存不可变快照

在 `articles` 增加：

- `target_platform_code VARCHAR(50) NULL`，建立索引。

新增一对一表 `article_generation_contexts`，以 `article_id` 作为主键和外键，建议字段：

- `entrypoint VARCHAR(40)`；
- `schema_version INT`；
- `target_platform_code VARCHAR(50)`；
- `prompt_template_id BIGINT NULL`；
- `prompt_template_name_snapshot VARCHAR(200)`；
- `prompt_template_updated_at_snapshot DATETIME NULL`；
- `prompt_template_content_snapshot`；
- `effective_prompt_snapshot`；
- `effective_prompt_sha256 CHAR(64)`；
- `platform_policy_version VARCHAR(100)`；
- `platform_policy_snapshot JSON`；
- `question_snapshot JSON NULL`；
- `model_label VARCHAR(120) NULL`；
- `generation_params JSON NULL`；
- `evidence_refs JSON NULL`；
- `created_at DATETIME`。

`target_platform_code` 在两处重复是有意的：Article 字段用于筛选和发布防错；Context 字段属于不可变历史快照。保存服务强制两者一致。

模板、问题和平台政策的快照由服务器根据 ID/版本读取权威数据。客户端只提供服务器无法自行得知的有效提示词、模型参数和证据引用。

**替代方案：**

- 把所有内容放入 `Article.metrics`：拒绝。该字段已用于可变发布指标，多平台/多账号写入还存在覆盖风险，不适合作为不可变审计来源。
- 只保存模板 ID：拒绝。模板可编辑，且真实提示词还包含平台政策、取材前言和重写反馈。
- 先建立完整模板版本表：暂缓。文章级精确快照已经满足复盘；模板历史浏览/回滚可以后续独立建设。

### 2. 内容平台代码不外键到发布 Platform

目标平台复用现有内容平台词表：`xiaohongshu`、`toutiao`、`wechat_mp`；`NULL` 表示未记录或通用。它不外键到 `Platform` 表，因为内容目标平台集合与已接入发布驱动集合并不完全相同。

平台代码验证收敛到一个共享模块，PromptTemplate Schema、MCP Payload、Pipeline config 与文章 Service 复用同一集合，避免多份常量漂移。

### 3. 平台政策使用代码内版本化注册表

新增共享的平台内容政策服务，以平台代码和不可变版本定位结构化规则。首期至少覆盖现有已知保存/发布硬约束，例如小红书标题上限与 Toutiao 标题上限。MCP 新增 `get_platform_content_policy(platform_code, version=None)`；未传版本返回 active 版本，传版本用于复盘或重试。

Writer 与 Verifier在一次 attempt 中使用同一个版本；保存服务根据该版本取权威政策快照并执行硬规则；发布任务创建时再次使用文章记录的政策语义或当前兼容政策复检。

政策变更必须创建新版本，不能原地修改旧版本。这样无需首期增加政策表，也能保证已有文章快照稳定。

**替代方案：**

- 政策只写在 Skill：拒绝。服务端不能防止旧 Skill 或直接 API 绕过。
- 立即建设运营可编辑政策表：暂缓。它引入审批、版本发布和缓存一致性问题，超出建议 8 的首期价值验证。

### 4. MCP 采用可选兼容参数，新 geo-goal 采用严格调用

扩展 `save_article`/`SaveArticleFromMcpPayload`：

- `target_platform_code: str | None`；
- `generation_context: GenerationContextInput | None`，包含 `entrypoint`、`effective_prompt`、`platform_policy_version`、`generation_params`、`evidence_refs`。
- `generation_context` 还携带目录读取时由服务端计算的
  `prompt_template_fingerprint` / `question_fingerprint`；保存时服务端重算并拒绝漂移。

`prompt_template_id`、`question_item_id`、`model_label`、`selected_games` 继续复用现有顶层参数；服务器据此建立权威快照，避免重复且不可信的客户端副本。

`entrypoint` 由保存端点根据调用路径/内容形态核对并落库，不能由客户端把 MCP 保存伪装成
Pipeline。若写作期间模板或问题被编辑，fingerprint 不匹配时返回冲突，调用方重新读取源数据后
重写；不允许把旧 effective prompt 与新权威快照组合后仍标成 `complete`。

Pipeline 在运行时选中模板时同样锁定模板 fingerprint，并传给 Writer。Writer 用新会话重读模板，
在任何外部模型调用前比较 fingerprint、正文和名称；发生变化则拒绝本次生成。比较通过后，模板
名称、正文、更新时间、scope、平台和启停状态全部取自同一次重读，不混合不同时点的字段。

旧客户端可暂不传新字段；升级后的 geo-goal 必须传完整字段。服务端返回 `complete`、`incomplete` 或 `not_recorded` 状态：

- `complete`：目标平台和所需 Context 字段完整；
- `incomplete`：文章来自可识别生成入口，但兼容调用缺少完整 Context；
- `not_recorded`：历史或手工文章无生成记录。

`get_article` 默认只返回 Context 摘要，新增显式 `include_generation_context` 才返回大字段。列表和 `list_today_loop_articles` 永不返回完整提示词。

`list_today_loop_articles` 增加 `target_platform_code` 过滤。`pick_quality_references` 增加平台过滤并返回 canonical platform code；只有全部样本匹配时，Skill 才能将它描述为“同平台基线”，不足时沿用留人工路径。

### 5. 有效提示词定义为应用可观察的组装结果

`effective_prompt_snapshot` 保存 GEO Orchestrator 明确组装并交给 Writer 的文本或规范化序列化结果，包括模板内容、平台政策、取材上下文、attempt/重写反馈。它不包含模型提供商隐藏指令或宿主不可观察上下文。

服务端对规范化 UTF-8 字节计算 SHA-256。请求上限为 256 KiB，并通过统一安全检查拒绝
Authorization、Cookie、已配置密钥值及常见 Token 形态。检查同时覆盖有效提示词、模板名称/
正文、模型标签、问题、生成参数与证据引用；MCP 动态模型环境变量解析出的密钥也作为只校验、
不持久化的敏感值参与扫描。日志不得输出完整快照。

### 6. 保存与发布采用相同领域校验器

新增共享领域服务：

- 验证内容平台代码；
- 验证模板 `is_enabled`、未删除、`scope=generation` 及平台兼容；
- 根据政策执行标题、正文等硬规则；
- 创建并验证 Context。

`save_article_from_mcp` 在单个事务中创建 Article、设置溯源字段并创建 Context；任一步失败均 rollback。

`_validated_task_inputs` 在创建任务和任务预览时检查每篇非空 `target_platform_code` 是否与任务平台相同，并按当前 active 政策执行平台硬规则。文章 Context 中的旧政策版本只用于审计，不用于绕过后续收紧的发布规则。历史 `NULL` 文章保留现有行为。

Pipeline 生成节点新增可选 `target_platform_code`。缺省保持通用旧行为；一旦配置，模板运行时选择和落库都使用该平台，后续分发到其他平台会被任务校验拒绝。

### 7. Skill 修改以外部仓库为权威发布源

`E:\geo-claude-plugins` 中：

- Orchestrator 解析平台，缺省为 `toutiao`，按平台选择模板/政策并传给两个子代理；
- Writer 使用政策组装有效提示词，并在 `save_article` 传平台与 Context；
- Verifier 使用同一政策版本，不再忽略 platform；
- 质量参照查询真实按平台过滤，不足四篇时不跨平台补齐后继续声称“同平台”；
- 事件与汇报包含平台和政策版本。

同时更新 `plugins/geo-goal/commands/goal.md` 的平台用法。实施前先安全同步该仓库到最新
`origin/main`，保留任何脏文件；修改三个 Skill 及双清单版本，并通过 Git → DB 正式 Skill
同步链路发布。`E:\geo` 内的 repo-local fallback/种子 Skill 已废弃，本变更不修改其模板或
bundle 版本，避免继续维护第二份 Skill。

## Risks / Trade-offs

- [另一个窗口新增 Alembic 迁移] → 已等 collector 迁移实现/测试稳定并复核单一 head，再创建
  `0074_article_platform_context`；未修改或重写 `0073`。
- [旧 MCP 客户端不提供新字段] → 参数先可选并报告 provenance 状态；升级后的 geo-goal 通过契约测试强制完整传参。
- [提示词包含秘密或体积过大] → 服务端限制 256 KiB、执行秘密检测、错误和日志只返回摘要/哈希。
- [代码内平台政策需要发版才能调整] → 首期换取可测试和可版本化；出现高频运营调整需求时再引入审批式政策存储。
- [保存时使用旧政策版本] → 只接受注册表中仍可解析的不可变版本；未知版本拒绝，不自动替换成 active。
- [平台专属文章不能继续任意多平台扇出] → 这是有意的防错约束；现有无目标平台文章继续兼容，多平台优化版本后续用独立 Article 关系设计。
- [“最终提示词”可能被误解为模型完整上下文] → API、字段文档和 UI 明确标注为 application-controlled snapshot，不做不可验证承诺。

## Migration Plan

1. 等待 `build-local-game-collector-pipeline` 的数据库迁移稳定，检查 `alembic heads`，从当时唯一真实 head 创建新 revision。
2. 部署向后兼容数据库结构：nullable Article 字段和独立 Context 表；历史数据不回填。
3. 部署后端共享平台注册表、政策工具、扩展后的可选 MCP 契约、读模型和服务端校验，并运行迁移/单元/集成测试。
4. 部署 Pipeline 可选平台字段和发布任务防错；验证现有无平台 Pipeline 与历史文章回归。
5. 安全同步并升级 `E:\geo-claude-plugins`，让新 geo-goal 开始严格提交平台和完整 Context。
6. 运行一篇 Toutiao 端到端证据测试：保存、读取完整快照、修改模板后重读、Verifier、创建匹配/错配发布任务。
7. 观察兼容调用的 `incomplete` 数量，再单独决定是否把 MCP 新字段提升为全局必填。

回滚时先回滚 Skill，使调用恢复旧形状，再回滚后端行为。新增 nullable 列和 Context 表保留，避免破坏已经产生的审计数据；不通过破坏性降级删除快照。

## Open Questions

无阻塞性问题。平台政策首期范围以现有可证实的硬约束为准；软偏好、指标学习和多平台文章变体另立变更。
