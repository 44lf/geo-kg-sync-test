"""Stable fingerprints for authoritative generation sources.

MCP writers fetch templates/questions before writing and submit these digests on
save. The server recomputes them from current rows so a concurrent edit cannot
silently combine an old effective prompt with a newer authoritative snapshot.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any


def _datetime_text(value: datetime | None) -> str | None:
    return value.isoformat(timespec="microseconds") if value is not None else None


def _fingerprint(payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def prompt_template_fingerprint(template: Any) -> str:
    """Fingerprint fields that define the selected generation template."""

    return _fingerprint(
        {
            "id": template.id,
            "name": template.name,
            "content": template.content,
            "scope": template.scope,
            "platform": template.platform,
            "is_enabled": bool(template.is_enabled),
            "is_deleted": bool(template.is_deleted),
            "updated_at": _datetime_text(getattr(template, "updated_at", None)),
        }
    )


def question_item_fingerprint(question_item: Any) -> str:
    """Fingerprint authoritative question fields preserved in provenance."""

    return _fingerprint(
        {
            "id": question_item.id,
            "record_id": question_item.record_id,
            "question_text": question_item.question_text,
            "category": question_item.category,
            "source_active": bool(question_item.source_active),
        }
    )
