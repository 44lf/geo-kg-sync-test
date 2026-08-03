"""Immutable, versioned content-platform policy registry.

The public lookup returns a fresh JSON-compatible dictionary. Internal registry
objects are frozen and registry mappings are read-only, so changing a returned
payload or an active-version pointer cannot mutate an already registered policy.
Policy changes must add a new version and explicitly move the active pointer.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

from server.app.modules.content_platforms.vocabulary import (
    CONTENT_PLATFORM_CODES,
    ContentPlatformCode,
    validate_content_platform_code,
)
from server.app.shared.errors import ValidationError

RuleOperator = Literal["max_length"]
RuleUnit = Literal["characters"]


@dataclass(frozen=True, slots=True)
class _HardRule:
    code: str
    field: Literal["title"]
    operator: RuleOperator
    limit: int
    unit: RuleUnit = "characters"

    def to_dict(self) -> dict[str, str | int]:
        return {
            "code": self.code,
            "field": self.field,
            "operator": self.operator,
            "limit": self.limit,
            "unit": self.unit,
        }


@dataclass(frozen=True, slots=True)
class _PlatformPolicy:
    platform_code: ContentPlatformCode
    version: str
    rules: tuple[_HardRule, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "platform_code": self.platform_code,
            "version": self.version,
            "rules": [rule.to_dict() for rule in self.rules],
        }


@dataclass(frozen=True, slots=True)
class PolicyViolation:
    """One measured hard-rule violation."""

    rule_code: str
    field: str
    operator: str
    limit: int
    unit: str
    measured: int

    def to_dict(self) -> dict[str, str | int]:
        return {
            "rule_code": self.rule_code,
            "field": self.field,
            "operator": self.operator,
            "limit": self.limit,
            "unit": self.unit,
            "measured": self.measured,
        }


class PlatformPolicyValidationError(ValidationError):
    """Raised when article content violates one or more platform hard rules."""

    def __init__(
        self,
        *,
        platform_code: ContentPlatformCode,
        policy_version: str,
        violations: tuple[PolicyViolation, ...],
    ) -> None:
        self.platform_code = platform_code
        self.policy_version = policy_version
        self.violations = violations
        details = "; ".join(
            f"{item.rule_code} measured={item.measured} limit={item.limit}" for item in violations
        )
        super().__init__(
            "Platform policy validation failed for "
            f"{platform_code!r} (version {policy_version!r}): {details}"
        )


_POLICY_DEFINITIONS = (
    _PlatformPolicy(
        platform_code="toutiao",
        version="toutiao-2026-07-29-v1",
        rules=(
            _HardRule(
                code="title.max_characters",
                field="title",
                operator="max_length",
                limit=50,
            ),
        ),
    ),
    _PlatformPolicy(
        platform_code="xiaohongshu",
        version="xiaohongshu-2026-07-29-v1",
        rules=(
            _HardRule(
                code="title.max_characters",
                field="title",
                operator="max_length",
                limit=20,
            ),
        ),
    ),
    _PlatformPolicy(
        platform_code="wechat_mp",
        version="wechat_mp-2026-07-29-v1",
        rules=(),
    ),
)

_registry_build: dict[ContentPlatformCode, dict[str, _PlatformPolicy]] = {
    code: {} for code in CONTENT_PLATFORM_CODES
}
for _policy in _POLICY_DEFINITIONS:
    _registry_build[_policy.platform_code][_policy.version] = _policy

PLATFORM_POLICY_REGISTRY: Mapping[ContentPlatformCode, Mapping[str, _PlatformPolicy]] = (
    MappingProxyType(
        {
            platform_code: MappingProxyType(dict(versions))
            for platform_code, versions in _registry_build.items()
        }
    )
)

ACTIVE_PLATFORM_POLICY_VERSIONS: Mapping[ContentPlatformCode, str] = MappingProxyType(
    {
        "toutiao": "toutiao-2026-07-29-v1",
        "xiaohongshu": "xiaohongshu-2026-07-29-v1",
        "wechat_mp": "wechat_mp-2026-07-29-v1",
    }
)


def _resolve_platform_content_policy(
    code: str,
    version: str | None = None,
) -> _PlatformPolicy:
    platform_code = validate_content_platform_code(code, allow_none=False)
    assert platform_code is not None
    selected_version = version or ACTIVE_PLATFORM_POLICY_VERSIONS[platform_code]
    policy = PLATFORM_POLICY_REGISTRY[platform_code].get(selected_version)
    if policy is None:
        raise ValidationError(
            f"Unknown content policy version for platform {platform_code!r}: {selected_version!r}"
        )
    return policy


def get_platform_content_policy(
    code: str,
    version: str | None = None,
) -> dict[str, object]:
    """Return the active or requested immutable policy as a fresh JSON payload."""

    return _resolve_platform_content_policy(code, version).to_dict()


def _measure_rule(rule: _HardRule, *, title: str, plain_text: str) -> int:
    if rule.field == "title" and rule.operator == "max_length":
        # 平台约束按可见标题计数；兼容既有 XHS 入库门禁的首尾空白处理。
        return len(title.strip())
    raise RuntimeError(f"Unsupported registered platform rule: {rule.code}")


def validate_article_for_platform(
    code: str,
    title: str,
    plain_text: str = "",
    policy_version: str | None = None,
) -> None:
    """Validate article text against one exact platform-policy version.

    Passing no version selects the active policy. Unknown platforms/versions and
    malformed article fields are client input errors. Known hard-rule violations
    raise :class:`PlatformPolicyValidationError`, a structured ``ValidationError``
    subtype suitable for both MCP save and publication-task boundaries.
    """

    if not isinstance(title, str):
        raise ValidationError("Article title must be a string")
    if not isinstance(plain_text, str):
        raise ValidationError("Article plain_text must be a string")

    policy = _resolve_platform_content_policy(code, policy_version)
    violations: list[PolicyViolation] = []
    for rule in policy.rules:
        measured = _measure_rule(rule, title=title, plain_text=plain_text)
        if rule.operator == "max_length" and measured > rule.limit:
            violations.append(
                PolicyViolation(
                    rule_code=rule.code,
                    field=rule.field,
                    operator=rule.operator,
                    limit=rule.limit,
                    unit=rule.unit,
                    measured=measured,
                )
            )

    if violations:
        raise PlatformPolicyValidationError(
            platform_code=policy.platform_code,
            policy_version=policy.version,
            violations=tuple(violations),
        )
