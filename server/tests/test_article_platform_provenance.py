"""平台感知文章生成、不可变溯源与发布防错契约。

这些用例只通过 ORM metadata 创建测试表，不依赖尚在变化的 collector Alembic revision。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any

import pytest

MCP_TOKEN = "article-provenance-test-token"
MCP_HEADERS = {"X-MCP-Token": MCP_TOKEN}


def _enable_mcp(monkeypatch) -> None:
    monkeypatch.setenv("GEO_MCP_TOKEN", MCP_TOKEN)
    from server.app.core.config import get_settings

    get_settings.cache_clear()


def _build_app(monkeypatch):
    """隔离 collector 在 create_app import 后才扩充 Base.metadata 的共享缓存时序。"""
    from server.tests.utils import build_test_app, invalidate_test_schema

    invalidate_test_schema()
    return build_test_app(monkeypatch)


def _seed_question(test_app, *, text: str = "怎样写一篇平台文章", category: str = "游戏") -> int:
    from server.app.modules.ai_generation.models import QuestionItem, QuestionPool

    with test_app.session_factory() as db:
        pool = QuestionPool(name="platform-provenance-pool", user_id=test_app.admin_id)
        db.add(pool)
        db.flush()
        item = QuestionItem(
            pool_id=pool.id,
            record_id=f"record-{text}",
            fields={},
            question_text=text,
            category=category,
            source_active=True,
            status="pending",
        )
        db.add(item)
        db.commit()
        return item.id


def _seed_template(
    test_app,
    *,
    name: str,
    content: str,
    platform: str | None = None,
    scope: str = "generation",
) -> int:
    from server.app.modules.prompt_templates.models import PromptTemplate

    with test_app.session_factory() as db:
        template = PromptTemplate(
            name=name,
            content=content,
            scope=scope,
            platform=platform,
            user_id=test_app.admin_id,
            is_enabled=True,
            is_deleted=False,
        )
        db.add(template)
        db.commit()
        return template.id


def _policy_version(platform_code: str) -> str:
    from server.app.modules.content_platforms import get_platform_content_policy

    return str(get_platform_content_policy(platform_code)["version"])


def _complete_save_payload(
    test_app,
    *,
    question_item_id: int,
    prompt_template_id: int,
    target_platform_code: str,
    title: str = "平台文章标题",
    effective_prompt: str = "模板正文\n平台规则\n写作材料\nattempt=1",
) -> dict[str, Any]:
    from server.app.modules.ai_generation.models import QuestionItem
    from server.app.modules.articles.generation_fingerprints import (
        prompt_template_fingerprint,
        question_item_fingerprint,
    )
    from server.app.modules.prompt_templates.models import PromptTemplate

    with test_app.session_factory() as db:
        template = db.get(PromptTemplate, prompt_template_id)
        question_item = db.get(QuestionItem, question_item_id)
        assert template is not None
        assert question_item is not None
        template_fingerprint = prompt_template_fingerprint(template)
        question_fingerprint = question_item_fingerprint(question_item)

    return {
        "question_item_id": question_item_id,
        "prompt_template_id": prompt_template_id,
        "user_id": test_app.admin_id,
        "title": title,
        "markdown_content": "正文第一段\n\n## 小标题\n\n正文第二段",
        "model_label": "writer-contract-test",
        "target_platform_code": target_platform_code,
        "generation_context": {
            "entrypoint": "mcp_loop",
            "effective_prompt": effective_prompt,
            "platform_policy_version": _policy_version(target_platform_code),
            "prompt_template_fingerprint": template_fingerprint,
            "question_fingerprint": question_fingerprint,
            "generation_params": {"temperature": 0.2, "attempt": 1},
            "evidence_refs": [{"kind": "game", "id": 17, "name": "测试游戏"}],
        },
    }


def _article_counts(test_app) -> tuple[int, int]:
    from server.app.modules.articles.models import Article, ArticleGenerationContext

    with test_app.session_factory() as db:
        return db.query(Article).count(), db.query(ArticleGenerationContext).count()


@pytest.mark.mysql
def test_mcp_save_legacy_and_template_compatibility_matrix(monkeypatch):
    """旧形状、同平台模板、通用模板成功；错平台和非 generation 模板零落库。"""
    from server.app.modules.articles.models import Article

    test_app = _build_app(monkeypatch)
    try:
        _enable_mcp(monkeypatch)
        question_id = _seed_question(test_app)
        toutiao_template = _seed_template(
            test_app,
            name="头条模板",
            content="头条模板正文",
            platform="toutiao",
        )
        generic_template = _seed_template(
            test_app,
            name="通用模板",
            content="通用模板正文",
        )
        xhs_template = _seed_template(
            test_app,
            name="小红书模板",
            content="小红书模板正文",
            platform="xiaohongshu",
        )
        format_template = _seed_template(
            test_app,
            name="排版模板",
            content="排版模板正文",
            scope="ai_format",
        )

        legacy = test_app.client.post(
            "/api/articles/save-from-mcp",
            headers=MCP_HEADERS,
            json={
                "question_item_id": question_id,
                "prompt_template_id": generic_template,
                "user_id": test_app.admin_id,
                "title": "兼容旧客户端",
                "markdown_content": "旧客户端正文",
            },
        )
        assert legacy.status_code == 200, legacy.text

        same_platform = test_app.client.post(
            "/api/articles/save-from-mcp",
            headers=MCP_HEADERS,
            json=_complete_save_payload(
                test_app,
                question_item_id=question_id,
                prompt_template_id=toutiao_template,
                target_platform_code="toutiao",
                title="同平台模板文章",
            ),
        )
        assert same_platform.status_code == 200, same_platform.text

        generic = test_app.client.post(
            "/api/articles/save-from-mcp",
            headers=MCP_HEADERS,
            json=_complete_save_payload(
                test_app,
                question_item_id=question_id,
                prompt_template_id=generic_template,
                target_platform_code="toutiao",
                title="通用模板文章",
            ),
        )
        assert generic.status_code == 200, generic.text

        before_rejections = _article_counts(test_app)
        wrong_platform = test_app.client.post(
            "/api/articles/save-from-mcp",
            headers=MCP_HEADERS,
            json=_complete_save_payload(
                test_app,
                question_item_id=question_id,
                prompt_template_id=xhs_template,
                target_platform_code="toutiao",
                title="错平台模板文章",
            ),
        )
        assert wrong_platform.status_code == 400, wrong_platform.text
        assert "platform mismatch" in wrong_platform.json()["detail"]
        assert _article_counts(test_app) == before_rejections

        wrong_scope = test_app.client.post(
            "/api/articles/save-from-mcp",
            headers=MCP_HEADERS,
            json=_complete_save_payload(
                test_app,
                question_item_id=question_id,
                prompt_template_id=format_template,
                target_platform_code="toutiao",
                title="错误用途模板文章",
            ),
        )
        assert wrong_scope.status_code == 400, wrong_scope.text
        assert "scope must be generation" in wrong_scope.json()["detail"]
        assert _article_counts(test_app) == before_rejections

        with test_app.session_factory() as db:
            rows = db.query(Article).order_by(Article.id).all()
            assert len(rows) == 3
            assert rows[0].target_platform_code is None
            assert rows[0].generation_context is None
            assert rows[1].target_platform_code == "toutiao"
            assert rows[1].generation_context is not None
            assert rows[2].target_platform_code == "toutiao"
            assert rows[2].generation_context is not None
    finally:
        test_app.cleanup()


@pytest.mark.mysql
def test_authoritative_snapshot_hash_immutable_and_explicit_full_read(monkeypatch):
    """模板/问题/政策由服务端盖章，模板后改不影响快照，完整上下文只在显式读取时出现。"""
    from server.app.modules.ai_generation.models import QuestionItem
    from server.app.modules.articles.models import ArticleGenerationContext
    from server.app.modules.prompt_templates.models import PromptTemplate

    test_app = _build_app(monkeypatch)
    try:
        _enable_mcp(monkeypatch)
        policy_response = test_app.client.get(
            "/api/mcp/content-platforms/toutiao/policy",
            headers=MCP_HEADERS,
        )
        assert policy_response.status_code == 200, policy_response.text
        active_policy = policy_response.json()
        assert active_policy["platform_code"] == "toutiao"
        assert active_policy["version"]

        question_id = _seed_question(
            test_app,
            text="服务端权威问题",
            category="权威分类",
        )
        template_id = _seed_template(
            test_app,
            name="服务端模板名",
            content="服务端模板正文 v1",
            platform="toutiao",
        )
        effective_prompt = "取材前言\n服务端模板正文 v1\n头条政策\n第一次写作反馈"
        payload = _complete_save_payload(
            test_app,
            question_item_id=question_id,
            prompt_template_id=template_id,
            target_platform_code="toutiao",
            effective_prompt=effective_prompt,
        )
        payload["generation_context"]["platform_policy_version"] = active_policy["version"]
        # 这两个字段只是 MCP UI 展示信息，不能覆盖服务端权威模板/问题快照。
        payload["prompt_template_name"] = "伪造模板名"
        payload["question_text_preview"] = "伪造问题"

        saved = test_app.client.post(
            "/api/articles/save-from-mcp",
            headers=MCP_HEADERS,
            json=payload,
        )
        assert saved.status_code == 200, saved.text
        article_id = saved.json()["article_id"]
        expected_hash = hashlib.sha256(effective_prompt.encode("utf-8")).hexdigest()

        with test_app.session_factory() as db:
            context = db.get(ArticleGenerationContext, article_id)
            assert context is not None
            assert context.prompt_template_name_snapshot == "服务端模板名"
            assert context.prompt_template_content_snapshot == "服务端模板正文 v1"
            assert context.question_snapshot == {
                "question_item_id": question_id,
                "category": "权威分类",
                "question_text": "服务端权威问题",
            }
            assert context.platform_policy_snapshot == active_policy
            assert context.effective_prompt_snapshot == effective_prompt
            assert context.effective_prompt_sha256 == expected_hash
            assert context.model_label == "writer-contract-test"
            assert context.generation_params == {"temperature": 0.2, "attempt": 1}
            assert context.evidence_refs == [{"kind": "game", "id": 17, "name": "测试游戏"}]

            template = db.get(PromptTemplate, template_id)
            question = db.get(QuestionItem, question_id)
            assert template is not None
            assert question is not None
            template.name = "服务端模板名 v2"
            template.content = "服务端模板正文 v2"
            question.category = "修改后分类"
            question.question_text = "修改后问题"
            db.commit()

        compact = test_app.client.get(
            f"/api/mcp/articles/{article_id}",
            headers=MCP_HEADERS,
        )
        assert compact.status_code == 200, compact.text
        compact_body = compact.json()
        assert compact_body["target_platform_code"] == "toutiao"
        assert compact_body["provenance_state"] == "complete"
        assert compact_body["platform_policy_version"] == active_policy["version"]
        assert compact_body["generation_context"] is None
        assert "effective_prompt_snapshot" not in compact_body

        full = test_app.client.get(
            f"/api/mcp/articles/{article_id}",
            headers=MCP_HEADERS,
            params={"include_generation_context": "true"},
        )
        assert full.status_code == 200, full.text
        full_context = full.json()["generation_context"]
        assert full_context["prompt_template_name_snapshot"] == "服务端模板名"
        assert full_context["prompt_template_content_snapshot"] == "服务端模板正文 v1"
        assert full_context["effective_prompt_snapshot"] == effective_prompt
        assert full_context["effective_prompt_sha256"] == expected_hash
        assert full_context["question_snapshot"]["question_text"] == "服务端权威问题"

        review = test_app.client.post(
            f"/api/articles/{article_id}/auto-review",
            headers=MCP_HEADERS,
            json={
                "decision": "approved",
                "score_total": 92,
                "pass_line": 80,
                "score_breakdown": {"platform_compliance": 100, "content_quality": 88},
                "reasoning": "头条平台硬规则与内容质量均通过",
                "decided_by": "claude-goal-verifier",
            },
        )
        assert review.status_code == 200, review.text
        assert review.json()["article_id"] == article_id
        assert review.json()["decision"] == "approved"
        assert review.json()["decided_by"] == "claude-goal-verifier"
    finally:
        test_app.cleanup()


@pytest.mark.mysql
def test_oversized_and_authorization_material_rejected_with_atomic_rollback(monkeypatch):
    """安全校验发生在 Article flush 后也必须回滚，错误不得回显授权值。"""
    test_app = _build_app(monkeypatch)
    try:
        _enable_mcp(monkeypatch)
        question_id = _seed_question(test_app)
        template_id = _seed_template(
            test_app,
            name="安全模板",
            content="安全模板正文",
            platform="toutiao",
        )

        oversized_prompt = "界" * ((256 * 1024 // 3) + 1)
        oversized_payload = _complete_save_payload(
            test_app,
            question_item_id=question_id,
            prompt_template_id=template_id,
            target_platform_code="toutiao",
            effective_prompt=oversized_prompt,
        )
        oversized = test_app.client.post(
            "/api/articles/save-from-mcp",
            headers=MCP_HEADERS,
            json=oversized_payload,
        )
        assert oversized.status_code == 400, oversized.text
        assert "256 KiB" in oversized.json()["detail"]
        assert _article_counts(test_app) == (0, 0)

        authorization_value = "do-not-persist-this-bearer-value"
        secret_payload = _complete_save_payload(
            test_app,
            question_item_id=question_id,
            prompt_template_id=template_id,
            target_platform_code="toutiao",
            effective_prompt=f"写作要求\nAuthorization: Bearer {authorization_value}",
        )
        rejected = test_app.client.post(
            "/api/articles/save-from-mcp",
            headers=MCP_HEADERS,
            json=secret_payload,
        )
        assert rejected.status_code == 400, rejected.text
        assert "authorization material" in rejected.json()["detail"]
        assert authorization_value not in rejected.json()["detail"]
        assert _article_counts(test_app) == (0, 0)

        for unsafe_prompt in (
            '{"api_key":"plain-json-secret-value"}',
            "Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJnZW8tdGVzdCJ9.signature123456789",
        ):
            unsafe_payload = _complete_save_payload(
                test_app,
                question_item_id=question_id,
                prompt_template_id=template_id,
                target_platform_code="toutiao",
                effective_prompt=unsafe_prompt,
            )
            rejected = test_app.client.post(
                "/api/articles/save-from-mcp",
                headers=MCP_HEADERS,
                json=unsafe_payload,
            )
            assert rejected.status_code == 400, rejected.text
            assert "authorization material" in rejected.json()["detail"]
            assert _article_counts(test_app) == (0, 0)

        rotated_secret = "rotated-fernet-key-value-for-test"
        monkeypatch.setenv("GEO_SECRET_KEYS", rotated_secret)
        from server.app.core.config import get_settings

        get_settings.cache_clear()
        rotated_payload = _complete_save_payload(
            test_app,
            question_item_id=question_id,
            prompt_template_id=template_id,
            target_platform_code="toutiao",
            effective_prompt=f"正常写作要求\n{rotated_secret}",
        )
        rotated = test_app.client.post(
            "/api/articles/save-from-mcp",
            headers=MCP_HEADERS,
            json=rotated_payload,
        )
        assert rotated.status_code == 400, rotated.text
        assert rotated_secret not in rotated.json()["detail"]
        assert _article_counts(test_app) == (0, 0)

        from server.app.modules.ai_models.models import AiModel

        dynamic_secret = "dynamic-model-secret-value-for-test"
        monkeypatch.setenv("GEO_TEST_DYNAMIC_MODEL_KEY", dynamic_secret)
        with test_app.session_factory() as db:
            model = db.query(AiModel).filter(AiModel.scope == "generation").first()
            assert model is not None
            model.api_key_env = "GEO_TEST_DYNAMIC_MODEL_KEY"
            db.commit()
        dynamic_payload = _complete_save_payload(
            test_app,
            question_item_id=question_id,
            prompt_template_id=template_id,
            target_platform_code="toutiao",
            effective_prompt=f"正常写作要求\n{dynamic_secret}",
        )
        dynamic = test_app.client.post(
            "/api/articles/save-from-mcp",
            headers=MCP_HEADERS,
            json=dynamic_payload,
        )
        assert dynamic.status_code == 400, dynamic.text
        assert dynamic_secret not in dynamic.json()["detail"]
        assert _article_counts(test_app) == (0, 0)

        unsafe_label_payload = _complete_save_payload(
            test_app,
            question_item_id=question_id,
            prompt_template_id=template_id,
            target_platform_code="toutiao",
        )
        unsafe_label_payload["model_label"] = dynamic_secret
        unsafe_label = test_app.client.post(
            "/api/articles/save-from-mcp",
            headers=MCP_HEADERS,
            json=unsafe_label_payload,
        )
        assert unsafe_label.status_code == 400, unsafe_label.text
        assert dynamic_secret not in unsafe_label.json()["detail"]
        assert _article_counts(test_app) == (0, 0)
    finally:
        test_app.cleanup()


@pytest.mark.mysql
def test_platform_filtered_lists_compact_states_and_loop_isolation(monkeypatch):
    """列表只回紧凑溯源；平台过滤排除其它平台、legacy 与历史 NULL。"""
    from server.app.modules.auto_review.models import AutoReviewDecision

    test_app = _build_app(monkeypatch)
    try:
        _enable_mcp(monkeypatch)
        question_id = _seed_question(test_app)
        generic_template = _seed_template(
            test_app,
            name="跨平台通用模板",
            content="通用正文",
        )

        toutiao = test_app.client.post(
            "/api/articles/save-from-mcp",
            headers=MCP_HEADERS,
            json=_complete_save_payload(
                test_app,
                question_item_id=question_id,
                prompt_template_id=generic_template,
                target_platform_code="toutiao",
                title="头条完整文章",
            ),
        )
        assert toutiao.status_code == 200, toutiao.text
        toutiao_id = toutiao.json()["article_id"]

        xhs = test_app.client.post(
            "/api/articles/save-from-mcp",
            headers=MCP_HEADERS,
            json=_complete_save_payload(
                test_app,
                question_item_id=question_id,
                prompt_template_id=generic_template,
                target_platform_code="xiaohongshu",
                title="小红书完整文章",
            ),
        )
        assert xhs.status_code == 200, xhs.text
        xhs_id = xhs.json()["article_id"]

        compatibility = test_app.client.post(
            "/api/articles/save-from-mcp",
            headers=MCP_HEADERS,
            json={
                "question_item_id": question_id,
                "prompt_template_id": generic_template,
                "user_id": test_app.admin_id,
                "title": "旧 MCP 不完整文章",
                "markdown_content": "兼容正文",
            },
        )
        assert compatibility.status_code == 200, compatibility.text
        compatibility_id = compatibility.json()["article_id"]

        historical = test_app.client.post(
            "/api/articles",
            json={
                "title": "历史手工文章",
                "content_json": {"type": "doc", "content": []},
                "content_html": "",
                "plain_text": "历史正文",
            },
        )
        assert historical.status_code == 200, historical.text
        historical_id = historical.json()["id"]

        with test_app.session_factory() as db:
            for article_id in (toutiao_id, xhs_id, compatibility_id):
                db.add(
                    AutoReviewDecision(
                        article_id=article_id,
                        decision="approved",
                        score_total=90,
                        decided_by="claude-goal-verifier",
                    )
                )
            db.commit()

        filtered = test_app.client.get(
            "/api/mcp/articles",
            headers=MCP_HEADERS,
            params={"target_platform_code": "toutiao"},
        )
        assert filtered.status_code == 200, filtered.text
        assert [item["id"] for item in filtered.json()] == [toutiao_id]
        item = filtered.json()[0]
        assert item["provenance_state"] == "complete"
        assert item["platform_policy_version"] == _policy_version("toutiao")
        assert "generation_context" not in item
        assert "effective_prompt_snapshot" not in json.dumps(item)

        all_articles = test_app.client.get("/api/mcp/articles", headers=MCP_HEADERS)
        assert all_articles.status_code == 200, all_articles.text
        by_id = {item["id"]: item for item in all_articles.json()}
        assert by_id[toutiao_id]["provenance_state"] == "complete"
        assert by_id[xhs_id]["provenance_state"] == "complete"
        assert by_id[compatibility_id]["provenance_state"] == "incomplete"
        assert by_id[historical_id]["provenance_state"] == "not_recorded"
        assert by_id[historical_id]["target_platform_code"] is None

        historical_detail = test_app.client.get(f"/api/articles/{historical_id}")
        assert historical_detail.status_code == 200, historical_detail.text
        assert historical_detail.json()["provenance_state"] == "not_recorded"
        assert historical_detail.json()["generation_context"] is None

        today = test_app.client.get(
            "/api/articles/today-loop-decisions",
            headers=MCP_HEADERS,
            params={"target_platform_code": "toutiao"},
        )
        assert today.status_code == 200, today.text
        assert today.json()["data"]["count"] == 1
        assert today.json()["data"]["items"] == [
            {
                "article_id": toutiao_id,
                "title": "头条完整文章",
                "decided_at": today.json()["data"]["items"][0]["decided_at"],
                "score_total": 90,
                "target_platform_code": "toutiao",
            }
        ]
    finally:
        test_app.cleanup()


@pytest.mark.mysql
def test_pipeline_writer_snapshots_the_prompt_used_before_concurrent_template_edit(monkeypatch):
    """LiteLLM 调用期间模板被编辑时，Context 仍须描述实际已发送的 v1。"""
    from types import SimpleNamespace

    from server.app.modules.ai_generation.article_writer import generate_article_from_prompt
    from server.app.modules.articles.models import Article, ArticleGenerationContext
    from server.app.modules.prompt_templates.models import PromptTemplate

    test_app = _build_app(monkeypatch)
    try:
        template_v1 = "模板 v1：围绕 {{问题}} 写作"
        template_id = _seed_template(
            test_app,
            name="Pipeline 模板 v1",
            content=template_v1,
            platform="toutiao",
        )
        rendered_question_text = "1. 已校验问题 A\n2. 已校验问题 B"
        captured_messages: list[dict[str, str]] = []

        def fake_completion(**kwargs):
            captured_messages.extend(kwargs["messages"])
            # 模拟运营人员恰好在真实 LiteLLM 请求期间把权威模板改成 v2。
            with test_app.session_factory() as db:
                template = db.get(PromptTemplate, template_id)
                assert template is not None
                template.name = "Pipeline 模板 v2"
                template.content = "模板 v2：这不是本次实际发送的内容"
                db.commit()
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content="# Pipeline 标题\n\nPipeline 正文")
                    )
                ]
            )

        monkeypatch.setattr("litellm.completion", fake_completion)
        article_id = generate_article_from_prompt(
            session_factory=test_app.session_factory,
            user_id=test_app.admin_id,
            template_content=template_v1,
            question_text=rendered_question_text,
            source_agent_name="Pipeline 回归测试",
            source_template_name="Pipeline 模板 v1",
            source_template_id=template_id,
            target_platform_code="toutiao",
            platform_policy_version=_policy_version("toutiao"),
        )

        assert len(captured_messages) == 2
        actual_user_prompt = captured_messages[1]["content"]
        assert "模板 v1" in actual_user_prompt
        assert rendered_question_text in actual_user_prompt
        assert "模板 v2" not in actual_user_prompt

        with test_app.session_factory() as db:
            template = db.get(PromptTemplate, template_id)
            article = db.get(Article, article_id)
            context = db.get(ArticleGenerationContext, article_id)
            assert template is not None
            assert article is not None
            assert context is not None
            assert template.name == "Pipeline 模板 v2"
            assert template.content == "模板 v2：这不是本次实际发送的内容"
            assert article.target_platform_code == "toutiao"
            assert context.entrypoint == "pipeline"
            assert context.prompt_template_name_snapshot == "Pipeline 模板 v1"
            assert context.prompt_template_content_snapshot == template_v1
            assert context.question_snapshot == {"rendered_question_text": rendered_question_text}

            effective_prompt = json.loads(context.effective_prompt_snapshot)
            assert effective_prompt["messages"] == captured_messages
            assert "模板 v1" in effective_prompt["messages"][1]["content"]
            assert "模板 v2" not in context.effective_prompt_snapshot
            assert (
                context.effective_prompt_sha256
                == hashlib.sha256(context.effective_prompt_snapshot.encode("utf-8")).hexdigest()
            )
    finally:
        test_app.cleanup()


@pytest.mark.mysql
def test_pipeline_writer_rejects_template_drift_between_selection_and_writer(monkeypatch):
    """Pipeline 选择后的模板指纹一旦变化，必须在调用外部模型前终止。"""
    from server.app.modules.ai_generation.article_writer import generate_article_from_prompt
    from server.app.modules.articles.generation_fingerprints import (
        prompt_template_fingerprint,
    )
    from server.app.modules.prompt_templates.models import PromptTemplate
    from server.app.shared.errors import ValidationError

    test_app = _build_app(monkeypatch)
    try:
        template_v1 = "选择时模板 v1：围绕 {{问题}} 写作"
        template_id = _seed_template(
            test_app,
            name="选择时模板 v1",
            content=template_v1,
            platform="toutiao",
        )
        with test_app.session_factory() as db:
            selected_template = db.get(PromptTemplate, template_id)
            assert selected_template is not None
            selected_fingerprint = prompt_template_fingerprint(selected_template)
            selected_name = selected_template.name

        with test_app.session_factory() as db:
            current_template = db.get(PromptTemplate, template_id)
            assert current_template is not None
            current_template.name = "Writer 前模板 v2"
            current_template.content = "Writer 前模板 v2：不是已选择的来源"
            db.commit()

        def unexpected_completion(**kwargs):
            raise AssertionError("external model must not be called after source drift")

        monkeypatch.setattr("litellm.completion", unexpected_completion)
        with pytest.raises(ValidationError, match="changed after pipeline selection"):
            generate_article_from_prompt(
                session_factory=test_app.session_factory,
                user_id=test_app.admin_id,
                template_content=template_v1,
                question_text="已选择的问题",
                source_agent_name="Pipeline 漂移测试",
                source_template_name=selected_name,
                source_template_id=template_id,
                source_template_fingerprint=selected_fingerprint,
                target_platform_code="toutiao",
            )
        assert _article_counts(test_app) == (0, 0)
    finally:
        test_app.cleanup()


@pytest.mark.mysql
def test_mcp_source_fingerprints_reject_drift_and_false_entrypoint(monkeypatch):
    """目录摘要必须随 save 带回；模板/问题漂移或伪装 Pipeline 都不能标 complete。"""
    from server.app.modules.ai_generation.models import QuestionItem
    from server.app.modules.prompt_templates.models import PromptTemplate

    test_app = _build_app(monkeypatch)
    try:
        _enable_mcp(monkeypatch)
        question_id = _seed_question(test_app, text="指纹问题 v1")
        template_id = _seed_template(
            test_app,
            name="指纹模板 v1",
            content="指纹模板正文 v1",
            platform="toutiao",
        )
        with test_app.session_factory() as db:
            question = db.get(QuestionItem, question_id)
            assert question is not None
            pool_id = question.pool_id

        templates = test_app.client.get(
            "/api/mcp/prompt-templates",
            headers=MCP_HEADERS,
            params={"scope": "generation", "platform": "toutiao"},
        )
        questions = test_app.client.get(
            f"/api/mcp/question-pools/{pool_id}/items",
            headers=MCP_HEADERS,
        )
        assert templates.status_code == 200, templates.text
        assert questions.status_code == 200, questions.text
        template_item = next(item for item in templates.json() if item["id"] == template_id)
        question_item = next(item for item in questions.json() if item["id"] == question_id)
        assert len(template_item["generation_fingerprint"]) == 64
        assert len(question_item["generation_fingerprint"]) == 64

        stale_template_payload = _complete_save_payload(
            test_app,
            question_item_id=question_id,
            prompt_template_id=template_id,
            target_platform_code="toutiao",
        )
        with test_app.session_factory() as db:
            template = db.get(PromptTemplate, template_id)
            assert template is not None
            template.content = "指纹模板正文 v2"
            db.commit()
        rejected_template = test_app.client.post(
            "/api/articles/save-from-mcp",
            headers=MCP_HEADERS,
            json=stale_template_payload,
        )
        assert rejected_template.status_code == 409, rejected_template.text
        assert "template changed" in rejected_template.json()["detail"]
        assert _article_counts(test_app) == (0, 0)

        stale_question_payload = _complete_save_payload(
            test_app,
            question_item_id=question_id,
            prompt_template_id=template_id,
            target_platform_code="toutiao",
        )
        with test_app.session_factory() as db:
            question = db.get(QuestionItem, question_id)
            assert question is not None
            question.question_text = "指纹问题 v2"
            db.commit()
        rejected_question = test_app.client.post(
            "/api/articles/save-from-mcp",
            headers=MCP_HEADERS,
            json=stale_question_payload,
        )
        assert rejected_question.status_code == 409, rejected_question.text
        assert "question changed" in rejected_question.json()["detail"]
        assert _article_counts(test_app) == (0, 0)

        false_entrypoint_payload = _complete_save_payload(
            test_app,
            question_item_id=question_id,
            prompt_template_id=template_id,
            target_platform_code="toutiao",
        )
        false_entrypoint_payload["generation_context"]["entrypoint"] = "pipeline"
        rejected_entrypoint = test_app.client.post(
            "/api/articles/save-from-mcp",
            headers=MCP_HEADERS,
            json=false_entrypoint_payload,
        )
        assert rejected_entrypoint.status_code == 400, rejected_entrypoint.text
        assert "entrypoint mismatch" in rejected_entrypoint.json()["detail"]
        assert _article_counts(test_app) == (0, 0)
    finally:
        test_app.cleanup()


@pytest.mark.mysql
def test_pipeline_rejects_dynamic_model_secret_before_external_call(monkeypatch):
    """Resolved DB/env model keys embedded in prompts must fail before LiteLLM sees them."""
    from server.app.modules.ai_generation.article_writer import generate_article_from_prompt
    from server.app.shared.errors import ValidationError

    test_app = _build_app(monkeypatch)
    try:
        template_id = _seed_template(
            test_app,
            name="Pipeline 安全模板",
            content="安全模板正文",
            platform="toutiao",
        )
        dynamic_secret = "pipeline-dynamic-model-secret-value"
        monkeypatch.setattr(
            "server.app.modules.ai_models.service.resolve_writing_engine",
            lambda db, model: ("test-model", dynamic_secret, None),
        )

        def unexpected_completion(**kwargs):
            raise AssertionError("external model must not be called")

        monkeypatch.setattr("litellm.completion", unexpected_completion)
        with pytest.raises(ValidationError, match="configured secret"):
            generate_article_from_prompt(
                session_factory=test_app.session_factory,
                user_id=test_app.admin_id,
                template_content="安全模板正文",
                question_text=f"请围绕材料写作：{dynamic_secret}",
                source_agent_name="Pipeline 安全测试",
                source_template_name="Pipeline 安全模板",
                source_template_id=template_id,
                target_platform_code="toutiao",
            )
        assert _article_counts(test_app) == (0, 0)
    finally:
        test_app.cleanup()


@pytest.mark.mysql
@pytest.mark.parametrize(
    "path",
    [
        "/api/quality-reference/pick",
        "/api/articles/today-loop-decisions",
    ],
)
def test_mcp_platform_filtered_endpoints_reject_invalid_platform_as_400(
    monkeypatch,
    path,
):
    """命名 ValidationError 必须交全局 400 handler，不能被 MCP 包装成 500。"""
    test_app = _build_app(monkeypatch)
    try:
        _enable_mcp(monkeypatch)
        response = test_app.client.get(
            path,
            headers=MCP_HEADERS,
            params={"platform_code": "not-a-platform"}
            if path.endswith("/pick")
            else {"target_platform_code": "not-a-platform"},
        )

        assert response.status_code == 400, response.text
        assert "Unsupported content platform code" in response.json()["detail"]
        assert "not-a-platform" in response.json()["detail"]
    finally:
        test_app.cleanup()


def test_public_mcp_tool_contract_forwards_platform_and_context(monkeypatch):
    """FastMCP wrapper 必须把平台、完整读取和平台过滤参数原样转给后端。"""
    import server.mcp.tools.action as action_tools
    import server.mcp.tools.catalog as catalog_tools

    post_calls: list[tuple[str, dict[str, Any]]] = []
    get_calls: list[tuple[str, dict[str, Any] | None]] = []

    async def fake_post(path: str, *, json: dict[str, Any]) -> dict[str, Any]:
        post_calls.append((path, json))
        return {"ok": True, "data": {"article_id": 1}, "error": None}

    async def fake_get(
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        get_calls.append((path, params))
        return {"ok": True, "data": {}, "error": None}

    monkeypatch.setattr(action_tools, "_apost", fake_post)
    monkeypatch.setattr(catalog_tools, "_aget", fake_get)
    context = {
        "entrypoint": "mcp_loop",
        "effective_prompt": "observable prompt",
        "platform_policy_version": "toutiao-2026-07-29-v1",
        "prompt_template_fingerprint": "a" * 64,
        "question_fingerprint": "b" * 64,
    }

    asyncio.run(
        action_tools.save_article(
            question_item_id=3,
            prompt_template_id=7,
            title="MCP contract",
            markdown_content="body",
            target_platform_code="toutiao",
            generation_context=context,
        )
    )
    assert post_calls == [
        (
            "/api/articles/save-from-mcp",
            {
                "question_item_id": 3,
                "prompt_template_id": 7,
                "user_id": action_tools._OPERATOR_USER_ID,
                "title": "MCP contract",
                "markdown_content": "body",
                "target_platform_code": "toutiao",
                "generation_context": context,
            },
        )
    ]

    asyncio.run(catalog_tools.get_article(11, include_generation_context=True))
    asyncio.run(catalog_tools.get_platform_content_policy("toutiao", version="v1"))
    asyncio.run(
        catalog_tools.list_today_loop_articles(
            target_platform_code="toutiao",
        )
    )
    asyncio.run(
        catalog_tools.pick_quality_references(
            category="游戏",
            platform_code="toutiao",
            k=4,
        )
    )

    assert get_calls[0] == (
        "/api/mcp/articles/11",
        {"include_generation_context": "true"},
    )
    assert get_calls[1] == (
        "/api/mcp/content-platforms/toutiao/policy",
        {"version": "v1"},
    )
    assert get_calls[2][0] == "/api/articles/today-loop-decisions"
    assert get_calls[2][1]["target_platform_code"] == "toutiao"
    assert get_calls[3] == (
        "/api/quality-reference/pick",
        {"category": "游戏", "platform_code": "toutiao", "k": 4},
    )


def _seed_publication_platform_and_account(
    test_app,
    *,
    code: str,
) -> int:
    from server.app.modules.accounts.models import Account
    from server.app.modules.system.models import Platform

    with test_app.session_factory() as db:
        platform = db.query(Platform).filter(Platform.code == code).first()
        if platform is None:
            platform = Platform(
                code=code,
                name=code,
                base_url=f"https://{code}.example.test",
                enabled=True,
            )
            db.add(platform)
            db.flush()
        account = Account(
            user_id=test_app.admin_id,
            platform_id=platform.id,
            display_name=f"{code}-account",
            platform_user_id=f"{code}-user",
            status="valid",
            state_path=f"browser_states/{code}/state.json",
            is_deleted=False,
        )
        db.add(account)
        db.commit()
        return account.id


def _create_approved_article(
    test_app,
    *,
    title: str,
    target_platform_code: str | None,
) -> int:
    from server.app.modules.articles.models import Article

    payload: dict[str, Any] = {
        "title": title,
        "content_json": {"type": "doc", "content": []},
        "content_html": "",
        "plain_text": "发布正文",
    }
    if target_platform_code is not None:
        payload["target_platform_code"] = target_platform_code
    created = test_app.client.post("/api/articles", json=payload)
    assert created.status_code == 200, created.text
    article_id = created.json()["id"]
    with test_app.session_factory() as db:
        article = db.get(Article, article_id)
        assert article is not None
        article.review_status = "approved"
        db.commit()
    return article_id


def _task_payload(
    *,
    article_id: int,
    platform_code: str,
    account_id: int,
    name: str,
) -> dict[str, Any]:
    return {
        "name": name,
        "task_type": "single",
        "article_id": article_id,
        "platform_code": platform_code,
        "accounts": [{"account_id": account_id}],
        "stop_before_publish": False,
    }


@pytest.mark.mysql
def test_publication_preview_and_create_enforce_platform_contract(monkeypatch):
    """预览与建任务共用：匹配成功、错配/硬规则非法拒绝、历史 NULL 继续兼容。"""
    from server.app.modules.tasks import service as task_service
    from server.app.modules.tasks.models import PublishRecord, PublishTask

    test_app = _build_app(monkeypatch)
    try:
        original_validate = task_service.validate_article_for_platform
        publication_policy_versions: list[str | None] = []

        def record_publication_policy(
            code: str,
            title: str,
            plain_text: str = "",
            policy_version: str | None = None,
        ) -> None:
            publication_policy_versions.append(policy_version)
            original_validate(code, title, plain_text, policy_version)

        monkeypatch.setattr(
            task_service,
            "validate_article_for_platform",
            record_publication_policy,
        )
        toutiao_account = _seed_publication_platform_and_account(test_app, code="toutiao")
        wechat_account = _seed_publication_platform_and_account(test_app, code="wechat_mp")

        matching_article = _create_approved_article(
            test_app,
            title="头条匹配文章",
            target_platform_code="toutiao",
        )
        matching_payload = _task_payload(
            article_id=matching_article,
            platform_code="toutiao",
            account_id=toutiao_account,
            name="匹配平台任务",
        )
        matching_preview = test_app.client.post("/api/tasks/preview", json=matching_payload)
        assert matching_preview.status_code == 200, matching_preview.text
        matching_create = test_app.client.post("/api/tasks", json=matching_payload)
        assert matching_create.status_code == 200, matching_create.text

        with test_app.session_factory() as db:
            baseline_counts = db.query(PublishTask).count(), db.query(PublishRecord).count()
        assert baseline_counts == (1, 1)

        mismatching_article = _create_approved_article(
            test_app,
            title="禁止错投文章",
            target_platform_code="toutiao",
        )
        mismatching_payload = _task_payload(
            article_id=mismatching_article,
            platform_code="wechat_mp",
            account_id=wechat_account,
            name="错配平台任务",
        )
        for endpoint in ("/api/tasks/preview", "/api/tasks"):
            rejected = test_app.client.post(endpoint, json=mismatching_payload)
            assert rejected.status_code == 400, rejected.text
            assert "target platform mismatch" in rejected.json()["detail"]
        with test_app.session_factory() as db:
            assert (
                db.query(PublishTask).count(),
                db.query(PublishRecord).count(),
            ) == baseline_counts

        invalid_article = _create_approved_article(
            test_app,
            title="头" * 51,
            target_platform_code="toutiao",
        )
        invalid_payload = _task_payload(
            article_id=invalid_article,
            platform_code="toutiao",
            account_id=toutiao_account,
            name="硬规则非法任务",
        )
        for endpoint in ("/api/tasks/preview", "/api/tasks"):
            rejected = test_app.client.post(endpoint, json=invalid_payload)
            assert rejected.status_code == 400, rejected.text
            detail = rejected.json()["detail"]
            assert "title.max_characters" in detail
            assert "measured=51" in detail
            assert "limit=50" in detail
        with test_app.session_factory() as db:
            assert (
                db.query(PublishTask).count(),
                db.query(PublishRecord).count(),
            ) == baseline_counts

        legacy_article = _create_approved_article(
            test_app,
            title="历史未记录平台文章",
            target_platform_code=None,
        )
        legacy_payload = _task_payload(
            article_id=legacy_article,
            platform_code="wechat_mp",
            account_id=wechat_account,
            name="历史兼容任务",
        )
        legacy_preview = test_app.client.post("/api/tasks/preview", json=legacy_payload)
        assert legacy_preview.status_code == 200, legacy_preview.text
        legacy_create = test_app.client.post("/api/tasks", json=legacy_payload)
        assert legacy_create.status_code == 200, legacy_create.text
        with test_app.session_factory() as db:
            assert (db.query(PublishTask).count(), db.query(PublishRecord).count()) == (2, 2)
        assert publication_policy_versions
        assert set(publication_policy_versions) == {None}
    finally:
        test_app.cleanup()
