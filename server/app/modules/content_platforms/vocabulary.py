"""Canonical vocabulary for article target platforms."""

from typing import Literal

from server.app.shared.errors import ValidationError

ContentPlatformCode = Literal["xiaohongshu", "toutiao", "wechat_mp"]

# The tuple is useful for deterministic API/schema output; the frozenset is the
# membership authority used by all runtime validation.
CONTENT_PLATFORM_CODES: tuple[ContentPlatformCode, ...] = (
    "xiaohongshu",
    "toutiao",
    "wechat_mp",
)
SUPPORTED_CONTENT_PLATFORM_CODES = frozenset(CONTENT_PLATFORM_CODES)


def validate_content_platform_code(
    code: str | None,
    *,
    allow_none: bool = True,
) -> ContentPlatformCode | None:
    """Return a canonical supported code or raise a client-visible validation error.

    Codes are deliberately not case-folded or otherwise guessed. Persisted values
    and policy registry keys must use one exact vocabulary. ``None`` represents the
    legacy/generic article path and is accepted unless the caller requires a policy.
    """

    if code is None:
        if allow_none:
            return None
        raise ValidationError("Content platform code is required")
    if code not in SUPPORTED_CONTENT_PLATFORM_CODES:
        supported = ", ".join(CONTENT_PLATFORM_CODES)
        raise ValidationError(
            f"Unsupported content platform code: {code!r}; supported codes: {supported}"
        )
    return code
