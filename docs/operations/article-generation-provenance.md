# 文章平台与生成溯源运维说明

本文说明 GEO 平台感知生文链路的字段语义、MCP 契约、兼容策略和上线顺序。

## 数据语义

- `Article.target_platform_code`：内容写作目标平台，当前支持
  `toutiao`、`xiaohongshu`、`wechat_mp`。`NULL` 表示历史、手工或未记录，
  不得依据后续发布记录猜测回填。
- `ArticleGenerationContext`：每篇文章至多一份不可变快照。保存后不随模板、问题或
  平台政策更新。
- `effective_prompt_snapshot`：仅表示 GEO 应用可观察并交给 Writer 的组装提示词，
  不包含模型提供商隐藏 system prompt、宿主开发者指令或不可观察的完整对话。
- `provenance_state`：
  - `complete`：平台、模型与必要快照齐全；
  - `incomplete`：可识别为生成文章，但兼容客户端未提交完整上下文；
  - `not_recorded`：历史或手工文章没有生成记录。

## MCP 契约

升级后的 geo-goal 调用 `save_article` 时，除既有问题、模板、标题、正文和模型字段外，
必须提交：

```json
{
  "target_platform_code": "toutiao",
  "generation_context": {
    "entrypoint": "mcp_loop",
    "effective_prompt": "GEO 应用实际组装并交给 Writer 的提示词",
    "platform_policy_version": "toutiao-2026-07-29-v1",
    "prompt_template_fingerprint": "从 list_prompt_templates 返回的 64 位摘要",
    "question_fingerprint": "从 list_question_items 返回的 64 位摘要",
    "generation_params": {
      "attempt": 1
    },
    "evidence_refs": [
      {
        "game_id": 123,
        "name": "示例游戏"
      }
    ]
  }
}
```

模板名称/正文、问题正文、平台政策正文与 SHA-256 均由后端根据 ID/版本生成权威快照，
客户端不得自行覆盖。模板/问题目录返回的 `generation_fingerprint` 必须在保存时原样带回；
若写作期间源记录发生变化，保存返回 409，调用方必须重新读取并重写，不能把旧提示词和新快照
拼成一条“完整”溯源。

相关只读工具：

- `get_platform_content_policy(platform_code, version?)`：读取 active 或指定政策版本；
- `get_article(article_id, include_generation_context=false)`：默认只返回精简溯源，
  显式传 `true` 才返回大字段；
- `list_today_loop_articles(..., target_platform_code?)`：按平台隔离 Loop 停止条件；
- `pick_quality_references(..., platform_code?)`：指定平台时只返回该平台参考，不足数量
  明确返回 `is_sufficient=false`。

## 服务端门禁

- 文章保存：模板必须启用、未删除、`scope=generation`，且为通用模板或与目标平台一致。
- 平台硬规则：保存前执行，创建发布任务/预览时再次执行。
- 发布错投：Article 平台非空时必须等于 PublishTask 平台；历史 `NULL` 文章保留旧行为。
- 安全：有效提示词最大 256 KiB；generation params 使用白名单；Authorization、Cookie、
  API Key、JWT、轮换密钥和 DB 模型环境变量解析出的密钥等内容拒绝入库；扫描覆盖有效提示词、
  模板名称/正文、模型标签、问题、参数与证据。Pipeline 选择模板时锁定来源 fingerprint，
  Writer 重读时若模板发生变化会在调用外部模型前拒绝；安全门禁也在外部调用前完成。
  错误和日志不回显快照正文或敏感值。

`GEO_MCP_TOKEN` 是全局管理员级 service credential，不是终端用户 token。持有者可从 service
视角读取全量文章，并可显式读取完整生成上下文；必须只配置在受控的 GEO MCP 进程，禁止分发给
普通用户或写入 Skill/日志。普通 Web 用户读取完整上下文仍受文章 owner/admin 权限约束。

## 上线顺序

1. 等采集器迁移稳定后，从实际唯一 Alembic head 接续文章平台迁移。
2. 先上线兼容后端：新 MCP 参数仍可选，历史文章不回填。
3. 再升级 geo-goal 插件，使新 `/goal` 强制传平台和完整上下文。
4. 用一篇本地 Toutiao 文章验证政策读取、保存、完整读取、模板修改后快照不变、
   Verifier、匹配发布预览与错配拒绝。
5. 观察 `incomplete` 调用来源，再单独决定是否把新参数提升为全局必填。

插件 Git → DB 同步、生产部署与正式发版必须单独获得发布确认；实现完成不等于已经上线。
