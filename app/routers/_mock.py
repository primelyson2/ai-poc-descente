"""Mock JSON 응답 공통 헬퍼.

- static/mock/*.json 을 읽어 그대로 반환
- 요청 X-Database 헤더를 X-Database-Echo 응답 헤더로 되돌려준다 (검증용)
- 인공 지연 (0.3s) 으로 비동기 UX 시연
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import Header
from fastapi.responses import JSONResponse

MOCK_DIR = Path(__file__).resolve().parent.parent.parent / "static" / "mock"


async def mock_response(filename: str, x_database: str | None = Header(default=None)) -> JSONResponse:
    await asyncio.sleep(0.3)
    payload = json.loads((MOCK_DIR / filename).read_text(encoding="utf-8"))
    headers = {"X-Database-Echo": x_database or ""}
    return JSONResponse(content=payload, headers=headers)


async def mock_payload(filename: str) -> Any:
    """직접 dict 가 필요할 때 사용 (헤더 echo 없음)."""
    await asyncio.sleep(0.3)
    return json.loads((MOCK_DIR / filename).read_text(encoding="utf-8"))
