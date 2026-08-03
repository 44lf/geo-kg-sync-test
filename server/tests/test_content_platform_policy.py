"""Shared content-platform vocabulary and immutable hard-policy registry."""

import json

import pytest

from server.app.modules.content_platforms import (
    CONTENT_PLATFORM_CODES,
    SUPPORTED_CONTENT_PLATFORM_CODES,
    PlatformPolicyValidationError,
    get_platform_content_policy,
    validate_article_for_platform,
    validate_content_platform_code,
)
from server.app.modules.content_platforms.policy import (
    ACTIVE_PLATFORM_POLICY_VERSIONS,
    PLATFORM_POLICY_REGISTRY,
)
from server.app.shared.errors import ValidationError


def test_content_platform_vocabulary_is_canonical_and_nullable_for_legacy_articles():
    assert CONTENT_PLATFORM_CODES == ("xiaohongshu", "toutiao", "wechat_mp")
    assert SUPPORTED_CONTENT_PLATFORM_CODES == frozenset(CONTENT_PLATFORM_CODES)
    assert validate_content_platform_code("toutiao") == "toutiao"
    assert validate_content_platform_code(None) is None


def test_content_platform_vocabulary_rejects_unknown_and_required_null_codes():
    with pytest.raises(ValidationError, match=r"Unsupported.*douyin"):
        validate_content_platform_code("douyin")
    with pytest.raises(ValidationError, match="required"):
        validate_content_platform_code(None, allow_none=False)


@pytest.mark.parametrize("platform_code", CONTENT_PLATFORM_CODES)
def test_active_platform_policy_is_versioned_and_json_serializable(platform_code):
    active = get_platform_content_policy(platform_code)
    by_version = get_platform_content_policy(platform_code, active["version"])

    assert active == by_version
    assert active["platform_code"] == platform_code
    assert active["version"] == ACTIVE_PLATFORM_POLICY_VERSIONS[platform_code]
    assert isinstance(active["rules"], list)
    json.dumps(active)


def test_policy_lookup_rejects_unknown_platform_and_version():
    with pytest.raises(ValidationError, match=r"Unsupported.*douyin"):
        get_platform_content_policy("douyin")
    with pytest.raises(ValidationError, match=r"Unknown.*toutiao.*missing-version"):
        get_platform_content_policy("toutiao", "missing-version")


def test_policy_registry_and_registered_versions_are_immutable():
    toutiao_version = ACTIVE_PLATFORM_POLICY_VERSIONS["toutiao"]

    with pytest.raises(TypeError):
        ACTIVE_PLATFORM_POLICY_VERSIONS["toutiao"] = "changed"  # type: ignore[index]
    with pytest.raises(TypeError):
        PLATFORM_POLICY_REGISTRY["toutiao"][toutiao_version] = object()  # type: ignore[index]

    # Lookup payloads are defensive copies: caller mutation cannot alter the
    # registered policy or any later article snapshot.
    returned = get_platform_content_policy("toutiao")
    returned["rules"][0]["limit"] = 1
    assert get_platform_content_policy("toutiao")["rules"][0]["limit"] == 50


def test_toutiao_title_limit_accepts_50_characters_and_rejects_51():
    validate_article_for_platform("toutiao", "头" * 50)

    with pytest.raises(PlatformPolicyValidationError) as caught:
        validate_article_for_platform("toutiao", "头" * 51)

    error = caught.value
    assert error.platform_code == "toutiao"
    assert error.policy_version == get_platform_content_policy("toutiao")["version"]
    assert [item.to_dict() for item in error.violations] == [
        {
            "rule_code": "title.max_characters",
            "field": "title",
            "operator": "max_length",
            "limit": 50,
            "unit": "characters",
            "measured": 51,
        }
    ]
    assert "measured=51 limit=50" in str(error)


def test_xiaohongshu_title_limit_accepts_20_characters_and_rejects_21():
    validate_article_for_platform("xiaohongshu", "红" * 20)

    with pytest.raises(PlatformPolicyValidationError) as caught:
        validate_article_for_platform("xiaohongshu", "红" * 21)

    assert caught.value.violations[0].limit == 20
    assert caught.value.violations[0].measured == 21


def test_validation_can_pin_a_known_version_and_rejects_unknown_version():
    version = get_platform_content_policy("toutiao")["version"]
    validate_article_for_platform("toutiao", "有效标题", policy_version=version)

    with pytest.raises(ValidationError, match=r"Unknown.*toutiao.*retired-version"):
        validate_article_for_platform(
            "toutiao",
            "有效标题",
            policy_version="retired-version",
        )


def test_wechat_policy_has_no_title_limit_in_initial_registry():
    validate_article_for_platform("wechat_mp", "公" * 200)
    assert get_platform_content_policy("wechat_mp")["rules"] == []
