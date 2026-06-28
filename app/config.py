"""config.yaml 로더 — 다중 ADB 설정.

구조 예시는 config.yaml.example 참조. 상대 경로(wallet_location/config_dir)는
project/ 루트 기준으로 절대경로화하여 oracledb 에 전달한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# project/ 루트 — app/ 의 부모 (config.yaml 이 여기에 놓인다)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.yaml"
WALLETS_DIR = PROJECT_ROOT / "wallets"


@dataclass
class DatabaseConfig:
    name: str
    label: str
    user: str
    password: str
    dsn: str
    wallet_location: str
    wallet_password: str
    config_dir: str
    asta: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "DatabaseConfig":
        required = ("name", "user", "password", "dsn")
        missing = [k for k in required if not d.get(k)]
        if missing:
            raise ValueError(
                f"config.yaml databases 항목에 필수키 누락: {missing} (name={d.get('name')!r})"
            )

        def _abs(p: str | None) -> str:
            if not p:
                return ""
            pp = Path(p)
            if not pp.is_absolute():
                pp = (PROJECT_ROOT / pp).resolve()
            return str(pp)

        return cls(
            name=d["name"],
            label=d.get("label") or d["name"],
            user=d["user"],
            password=d["password"],
            dsn=d["dsn"],
            wallet_location=_abs(d.get("wallet_location")),
            wallet_password=d.get("wallet_password", "") or "",
            config_dir=_abs(d.get("config_dir") or d.get("wallet_location")),
            asta=d.get("asta") or {},
        )


@dataclass
class AppConfig:
    default_database: str
    databases: list[DatabaseConfig]
    # 접근제어용 사전공유 키 (상위 레벨). 빈 문자열이면 인증 비활성.
    access_key: str = ""
    # 키 분실 복구 시 현재 키를 받을 관리자 이메일.
    admin_email: str = ""
    # 메일 발송용 SMTP 설정 (host/port/user/password/from/security). 비면 발송 불가.
    smtp: dict = field(default_factory=dict)

    def get(self, name: str) -> DatabaseConfig | None:
        return next((d for d in self.databases if d.name == name), None)

    def names(self) -> list[str]:
        return [d.name for d in self.databases]


def load_raw(path: str | Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    """config.yaml 을 원본 dict 그대로 읽는다 (쓰기/수정용 — 상대경로 보존)."""
    p = Path(path)
    if not p.exists():
        return {"default_database": "", "databases": []}
    with p.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {"default_database": "", "databases": []}


def save_raw(raw: dict[str, Any], path: str | Path = DEFAULT_CONFIG_PATH) -> None:
    """원본 dict 를 config.yaml 로 저장 (한글/순서 보존)."""
    p = Path(path)
    with p.open("w", encoding="utf-8") as f:
        yaml.safe_dump(raw, f, allow_unicode=True, sort_keys=False, default_flow_style=False)


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> AppConfig:
    # config.yaml 이 없거나 databases 가 비어 있어도 빈 설정으로 기동한다.
    # (신규 Oracle Linux 설치 후 "Database 관리" 화면에서 첫 DB 를 등록할 수 있도록)
    p = Path(path)
    if not p.exists():
        return AppConfig(default_database="", databases=[])
    with p.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    access_key = (raw.get("access_key") or "").strip()
    admin_email = (raw.get("admin_email") or "").strip()
    smtp = raw.get("smtp") or {}
    extra = {"access_key": access_key, "admin_email": admin_email, "smtp": smtp}
    items = raw.get("databases") or []
    dbs = [DatabaseConfig.from_dict(d) for d in items]
    if not dbs:
        return AppConfig(default_database="", databases=[], **extra)
    default = raw.get("default_database") or dbs[0].name
    if not any(d.name == default for d in dbs):
        default = dbs[0].name
    return AppConfig(default_database=default, databases=dbs, **extra)
