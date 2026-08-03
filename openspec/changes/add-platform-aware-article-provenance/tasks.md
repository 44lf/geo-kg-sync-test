## 1. Preflight and conflict control

- [x] 1.1 Confirm the collector change no longer has an unstable migration, run `alembic heads`, and record the single real parent revision without assuming that it is `0073`.
- [x] 1.2 Recheck `E:\geo` dirty files and establish a non-overlap map so this change preserves collector and user edits.
- [x] 1.3 Recheck `E:\geo-claude-plugins` local/origin state, preserve its dirty files, and determine the latest manifest version before any plugin edit.

## 2. Contract-first tests

- [x] 2.1 Add tests for the shared content-platform vocabulary, active/versioned policy lookup, unknown versions, and Toutiao/XHS hard constraints.
- [x] 2.2 Add article MCP save tests for platform/template compatibility, authoritative snapshots, SHA-256, size/secret rejection, atomic rollback, and legacy optional inputs.
- [x] 2.3 Add article read/list tests for target-platform filtering, provenance states, compact summaries, explicit full context, and historical null compatibility.
- [x] 2.4 Add MCP tool contract tests covering `save_article`, `get_article`, `get_platform_content_policy`, platform-filtered `list_today_loop_articles`, and platform-filtered quality references.
- [x] 2.5 Add publication task/preview tests proving matching, mismatching, hard-rule-invalid, and legacy-null article behavior.
- [x] 2.6 Add Pipeline tests proving optional target-platform propagation, platform-aware template selection, and legacy platform-less node compatibility.

## 3. Database and article model

- [x] 3.1 Create the Alembic revision from the verified current head to add indexed nullable `articles.target_platform_code` and the one-to-one `article_generation_contexts` table; do not backfill historical rows.
- [x] 3.2 Add the Article target-platform field, generation-context model/relationship, and delete behavior without changing unrelated collector models.
- [x] 3.3 Extend Article create/read/list schemas and service filtering with target-platform and compact provenance state/summary.
- [x] 3.4 Implement explicit full generation-context serialization for authorized detail reads without placing snapshots in list responses.

## 4. Platform policy and provenance domain services

- [x] 4.1 Centralize supported content-platform codes so PromptTemplate, Article, MCP, and Pipeline validation use one vocabulary.
- [x] 4.2 Implement the immutable versioned platform-policy registry and structured hard-rule validation, including existing Toutiao and XHS title constraints.
- [x] 4.3 Implement the server-side template validator for enabled, non-deleted, `generation` scope and generic-or-matching platform compatibility.
- [x] 4.4 Implement generation-context construction from authoritative template/question/policy data plus client-observable prompt metadata.
- [x] 4.5 Implement UTF-8 SHA-256, the 256 KiB limit, configured-secret/authorization-material rejection, and redacted logging/error behavior.

## 5. Article APIs and GEO MCP tools

- [x] 5.1 Extend `SaveArticleFromMcpPayload` and `save_article` with `target_platform_code` and optional structured generation context while preserving the legacy call shape.
- [x] 5.2 Refactor MCP article save so validation, Article creation, provenance fields, usage updates, and context creation commit or roll back atomically.
- [x] 5.3 Extend article detail/list MCP reads with compact provenance and an explicit full-context option.
- [x] 5.4 Add `get_platform_content_policy` to the backend MCP catalog and public MCP tool registry.
- [x] 5.5 Add `target_platform_code` filtering to article list and `list_today_loop_articles`, excluding null/other-platform rows from filtered results.
- [x] 5.6 Add platform filtering and canonical platform output to `pick_quality_references`; return insufficiency instead of cross-platform substitution.

## 6. Pipeline and publication enforcement

- [x] 6.1 Add optional `target_platform_code` to Pipeline generation/compose node configs and editor/API types without migrating existing Pipeline snapshots.
- [x] 6.2 Propagate configured platform through runtime template resolution, article generation, and persisted Article metadata.
- [x] 6.3 Apply shared hard-rule validation at Pipeline/MCP save boundaries and ensure known Toutiao violations are rejected before driver-side truncation.
- [x] 6.4 Apply target-platform matching and hard-rule validation in shared publication-task input validation so task creation and preview behave identically.

## 7. geo-goal plugin integration

- [x] 7.1 Safely sync `E:\geo-claude-plugins` from its current `origin/main` while preserving dirty and untracked user files.
- [x] 7.2 Update `geo-goal-orchestrator` and `commands/goal.md` to parse/default platform, select compatible templates/policies/references, and emit platform/version events.
- [x] 7.3 Update `geo-article-writer` to require orchestrated platform context, assemble the observable effective prompt, and submit the new save contract.
- [x] 7.4 Update `geo-article-verifier` to require the same platform/policy version, run the mechanical platform gate, and stop claiming unverified same-platform references.
- [x] 7.5 Confirm GEO's repo-local fallback Skill bundle is deprecated and leave its templates and bundle version unchanged.
- [x] 7.6 Extend dual-host plugin semantic validation/tests for parse → template → writer → save → reference → verifier → event propagation.
- [x] 7.7 Bump both plugin manifests from the latest upstream version and prepare the Git → DB sync handoff; do not publish or deploy without explicit release approval.

## 8. Verification and handoff

- [x] 8.1 Run targeted backend unit/integration tests, MCP registry/count tests, Pipeline tests, and plugin dual-host validation without relying on the collector's incomplete test schema.
- [x] 8.2 Run migration upgrade/downgrade/upgrade on an isolated database and verify existing null-platform Articles remain readable.
- [x] 8.3 Run a local Toutiao end-to-end proof covering policy retrieval, write/save, full provenance read, template mutation with unchanged snapshot, verification, matching publication preview, and rejected mismatch.
- [x] 8.4 Perform an independent code/spec review for security, compatibility, transaction boundaries, and false provenance claims; resolve all blocking findings.
- [x] 8.5 Update operator/MCP documentation and record the remaining production Skill sync/release step as requiring explicit user approval.
