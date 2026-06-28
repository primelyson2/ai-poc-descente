"""Disabled Source DB direct access module.

OADT2 ASTA production/runtime code must not connect to the Source DB directly.
All Source DB work must go through ADB ORDS/PLSQL and the allowlisted ADB DB Link
Source helper path.  This module remains only as a hard-fail compatibility shim
for any stale imports/tests/scripts that still reference the old helper name.

작성자: 도상훈
파일 용도: Source DB 직접 접속 경로를 영구 차단하는 호환성 shim이다."""
from __future__ import annotations

from typing import Any

DISABLED_REASON = "SOURCE DIRECT DB ACCESS IS DISABLED; use ADB ORDS/PLSQL + DB Link only"


def should_attempt_source_direct(payload: dict[str, Any], ords_result: dict[str, Any]) -> bool:
    """Source direct fallback is permanently disabled."""
    return False


def apply_source_direct_fallback(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Hard-fail stale callers so direct Source DB access cannot silently run."""
    raise RuntimeError(DISABLED_REASON)


def apply_source_direct_advisor_repair(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Hard-fail stale callers so direct Source DB advisor repair cannot run."""
    raise RuntimeError(DISABLED_REASON)
