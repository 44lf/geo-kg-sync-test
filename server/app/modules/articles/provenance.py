"""文章生成平台契约与不可变溯源快照构造。"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from server.app.core.config import get_settings
from server.app.modules.articles.models import ArticleGenerationContext
from server.app.modules.content_platforms import (
    get_platform_content_policy,
    validate_content_platform_code,
)
from server.app.shared.errors import ValidationError

MAX_EFFECTIVE_PROMPT_BYTES = 256 * 1024
MAX_CONTEXT_JSON_BYTES = 64 * 1024

_AUTH_MATERIAL_RE = re.compile(
    r"""(?ix)
    ["']?(?:authorization|proxy-authorization|cookie|set-cookie|
    x-mcp-token|api[_-]?key|access[_-]?token)["']?
    \s*[:=]\s*["']?(?:bearer\s+)?[^\s"',;}]+
    """
)
_COMMON_SECRET_RE = re.compile(r"\b(?:sk|ak)-[A-Za-z0-9_-]{16,}\b")
_BEARER_TOKEN_RE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}")
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")


@dataclass(frozen=True)
class GenerationContextSpec:
    entrypoint: str
    effective_prompt: str
    platform_policy_version: str
    generation_params: dict[str, Any] | None = None
    evidence_refs: list[Any] | dict[str, Any] | None = None
    question_snapshot: dict[str, Any] | None = None
    # Validation-only values. They are never persisted or logged.
    additional_secret_values: tuple[str, ...] = ()


def validate_generation_template(template: Any, target_platform_code: str | None) -> None:
    """校验模板的生文用途和目标平台兼容性。

    target_platform_code=None 是兼容旧 MCP 调用：仍强制 generation/启用/未删，
    但不推断也不拒绝历史客户端传入的平台专属模板。
    """

    if getattr(template, "is_deleted", False):
        raise ValidationError(f"prompt_template deleted: id={template.id}")
    if not getattr(template, "is_enabled", False):
        raise ValidationError(f"prompt_template disabled: id={template.id}")
    if getattr(template, "scope", None) != "generation":
        raise ValidationError(
            f"prompt_template scope must be generation: id={template.id}, "
            f"scope={getattr(template, 'scope', None)}"
        )
    if target_platform_code is None:
        return
    validate_content_platform_code(target_platform_code, allow_none=False)
    template_platform = getattr(template, "platform", None)
    if template_platform is not None and template_platform != target_platform_code:
        raise ValidationError(
            "prompt_template platform mismatch: "
            f"article={target_platform_code}, template={template_platform}"
        )


def _configured_secret_values() -> list[str]:
    settings = get_settings()
    values: list[str] = []
    for field in (
        "jwt_secret",
        "feishu_app_secret",
        "ai_api_key",
        "ai_format_api_key",
        "minio_secret_key",
        "baidu_api_key",
        "game_landscape_api_key",
        "mcp_token",
        "secret_key",
    ):
        value = getattr(settings, field, None)
        if isinstance(value, str) and len(value) >= 8:
            values.append(value)
    secret_keys = getattr(settings, "secret_keys", "")
    if isinstance(secret_keys, str):
        values.extend(
            key for key in (item.strip() for item in secret_keys.split(",")) if len(key) >= 8
        )
    for engine in getattr(settings, "ai_engines", []) or []:
        value = getattr(engine, "api_key", None)
        if isinstance(value, str) and len(value) >= 8:
            values.append(value)
    return values


def _validate_no_secret_material(
    value: str,
    *,
    field_name: str,
    additional_secret_values: tuple[str, ...] = (),
) -> None:
    if (
        _AUTH_MATERIAL_RE.search(value)
        or _COMMON_SECRET_RE.search(value)
        or _BEARER_TOKEN_RE.search(value)
        or _JWT_RE.search(value)
    ):
        raise ValidationError(f"{field_name} contains authorization material")
    for secret in (*_configured_secret_values(), *additional_secret_values):
        if not isinstance(secret, str) or len(secret) < 8:
            continue
        if secret in value:
            raise ValidationError(f"{field_name} contains a configured secret")


def validate_effective_prompt_snapshot(
    effective_prompt: str,
    *,
    additional_secret_values: tuple[str, ...] = (),
) -> str:
    """验证并返回原样提示词；错误不回显敏感正文。"""

    prompt_bytes = effective_prompt.encode("utf-8")
    if len(prompt_bytes) > MAX_EFFECTIVE_PROMPT_BYTES:
        raise ValidationError("effective_prompt exceeds 256 KiB application snapshot limit")
    _validate_no_secret_material(
        effective_prompt,
        field_name="effective_prompt",
        additional_secret_values=additional_secret_values,
    )
    return effective_prompt


def validate_generation_metadata_text(
    value: str | None,
    *,
    field_name: str,
    additional_secret_values: tuple[str, ...] = (),
) -> None:
    """Reject authorization/configured-secret material in persisted text metadata."""

    if value is None:
        return
    _validate_no_secret_material(
        value,
        field_name=field_name,
        additional_secret_values=additional_secret_values,
    )


def _validate_context_value(
    value: Any,
    *,
    field_name: str,
    additional_secret_values: tuple[str, ...] = (),
) -> None:
    if value is None:
        return
    serialized = json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
    if len(serialized.encode("utf-8")) > MAX_CONTEXT_JSON_BYTES:
        raise ValidationError(f"{field_name} exceeds 64 KiB snapshot limit")
    _validate_no_secret_material(
        serialized,
        field_name=field_name,
        additional_secret_values=additional_secret_values,
    )


def effective_prompt_sha256(effective_prompt: str) -> str:
    return hashlib.sha256(effective_prompt.encode("utf-8")).hexdigest()


def build_generation_context(
    *,
    article_id: int,
    target_platform_code: str,
    template: Any,
    question_item: Any | None,
    model_label: str | None,
    spec: GenerationContextSpec,
) -> ArticleGenerationContext:
    """从服务端权威对象构造一份新的、之后不可更新的 Context。"""

    validate_content_platform_code(target_platform_code, allow_none=False)
    validate_generation_template(template, target_platform_code)
    effective_prompt = validate_effective_prompt_snapshot(
        spec.effective_prompt,
        additional_secret_values=spec.additional_secret_values,
    )
    validate_generation_metadata_text(
        str(getattr(template, "name", "")),
        field_name="prompt_template_name",
        additional_secret_values=spec.additional_secret_values,
    )
    validate_generation_metadata_text(
        str(getattr(template, "content", "")),
        field_name="prompt_template_content",
        additional_secret_values=spec.additional_secret_values,
    )
    validate_generation_metadata_text(
        model_label,
        field_name="model_label",
        additional_secret_values=spec.additional_secret_values,
    )
    _validate_context_value(
        spec.generation_params,
        field_name="generation_params",
        additional_secret_values=spec.additional_secret_values,
    )
    _validate_context_value(
        spec.evidence_refs,
        field_name="evidence_refs",
        additional_secret_values=spec.additional_secret_values,
    )
    policy = get_platform_content_policy(
        target_platform_code,
        version=spec.platform_policy_version,
    )
    question_snapshot = spec.question_snapshot
    if question_item is not None:
        question_snapshot = {
            "question_item_id": question_item.id,
            "category": question_item.category,
            "question_text": question_item.question_text,
        }
    _validate_context_value(
        question_snapshot,
        field_name="question_snapshot",
        additional_secret_values=spec.additional_secret_values,
    )

    return ArticleGenerationContext(
        article_id=article_id,
        schema_version=1,
        entrypoint=spec.entrypoint,
        target_platform_code=target_platform_code,
        prompt_template_id=template.id,
        prompt_template_name_snapshot=template.name,
        prompt_template_updated_at_snapshot=getattr(template, "updated_at", None),
        prompt_template_content_snapshot=template.content,
        effective_prompt_snapshot=effective_prompt,
        effective_prompt_sha256=effective_prompt_sha256(effective_prompt),
        platform_policy_version=policy["version"],
        platform_policy_snapshot=policy,
        question_snapshot=question_snapshot,
        model_label=model_label,
        generation_params=spec.generation_params,
        evidence_refs=spec.evidence_refs,
    )
