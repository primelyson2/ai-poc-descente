"""FastAPI dependencies — X-Database 헤더를 검증하여 DB 이름을 반환."""
from __future__ import annotations

from fastapi import Header, HTTPException

from app import db
from app.config import AppConfig

_app_config: AppConfig | None = None


def set_config(cfg: AppConfig) -> None:
    global _app_config
    _app_config = cfg


def get_config() -> AppConfig | None:
    return _app_config


def current_db(x_database: str | None = Header(default=None)) -> str:
    if _app_config is None:
        raise HTTPException(status_code=500, detail={"error": "config not loaded"})
    name = (x_database or "").strip() or _app_config.default_database
    if not any(d.name == name for d in _app_config.databases):
        raise HTTPException(status_code=400, detail={"error": "unknown database", "database": name})
    if db.statuses.get(name) != "ok":
        raise HTTPException(
            status_code=503,
            detail={"error": "database unavailable", "database": name},
        )
    return name
