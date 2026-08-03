"""Shared content-platform vocabulary and versioned hard-policy validation.

This package is intentionally independent from publication-driver registration:
content targets can exist before GEO has a corresponding publishing driver.
"""

from server.app.modules.content_platforms.policy import (
    PlatformPolicyValidationError,
    get_platform_content_policy,
    validate_article_for_platform,
)
from server.app.modules.content_platforms.vocabulary import (
    CONTENT_PLATFORM_CODES,
    SUPPORTED_CONTENT_PLATFORM_CODES,
    ContentPlatformCode,
    validate_content_platform_code,
)

__all__ = [
    "CONTENT_PLATFORM_CODES",
    "SUPPORTED_CONTENT_PLATFORM_CODES",
    "ContentPlatformCode",
    "PlatformPolicyValidationError",
    "get_platform_content_policy",
    "validate_article_for_platform",
    "validate_content_platform_code",
]
