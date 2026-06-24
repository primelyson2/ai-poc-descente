"""ADB 등록 관리 API — 목록/상세/생성/수정/삭제/연결테스트 + Wallet 업로드.

config.yaml 을 단일 출처로 두고, 변경 시 파일을 다시 써서 메모리 설정(deps)과
풀(db.pools)을 함께 갱신한다. 비밀 필드(user 제외 password/wallet_password)는
응답에 절대 포함하지 않는다.
"""
from __future__ import annotations

import io
import re
import shutil
import zipfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app import db, deps
from app.config import (
    WALLETS_DIR,
    DatabaseConfig,
    load_config,
    load_raw,
    save_raw,
)

router = APIRouter(tags=["databases"])

_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


# ───────────────────────── 유틸 ─────────────────────────
def _reload_into_memory():
    """config.yaml 을 다시 읽어 deps 의 AppConfig 를 교체하고 반환."""
    cfg = load_config()
    deps.set_config(cfg)
    return cfg


def _detail(d: DatabaseConfig, is_default: bool) -> dict:
    """편집 폼용 상세 — 비밀번호류는 존재 여부(bool)만 노출."""
    wallet_dir = Path(d.wallet_location) if d.wallet_location else None
    has_wallet = bool(wallet_dir and wallet_dir.exists() and any(wallet_dir.iterdir()))
    return {
        "name": d.name,
        "label": d.label,
        "user": d.user,
        "dsn": d.dsn,
        "wallet_location": d.wallet_location,
        "has_wallet": has_wallet,
        "has_wallet_password": bool(d.wallet_password),
        "status": db.statuses.get(d.name, "unavailable"),
        "is_default": is_default,
    }


def _parse_tns_aliases(text: str) -> list[str]:
    """tnsnames.ora 에서 net service name(별칭) 목록 추출. 예: ailakehouse_high."""
    aliases: list[str] = []
    for line in text.splitlines():
        m = re.match(r"^\s*([A-Za-z0-9_]+)\s*=", line)
        if m:
            aliases.append(m.group(1))
    # 중복 제거(순서 유지)
    seen: set[str] = set()
    out = []
    for a in aliases:
        if a not in seen:
            seen.add(a)
            out.append(a)
    return out


def _tnsnames_from_zip(data: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for member in zf.namelist():
                if Path(member).name.lower() == "tnsnames.ora":
                    return zf.read(member).decode("utf-8", "replace")
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail={"error": "유효한 zip 파일이 아닙니다"})
    return ""


def _extract_wallet(data: bytes, dest: Path) -> None:
    """Wallet zip 을 dest 디렉터리에 평탄화하여 추출 (기존 내용 교체).

    ADB Wallet zip 은 파일이 루트에 평평하게 들어있거나 단일 상위 폴더로 감싸여
    있을 수 있어, 멤버의 basename 만으로 펼친다(zip-slip 방지 겸용)."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail={"error": "유효한 zip 파일이 아닙니다"})

    has_tns = any(Path(m).name.lower() == "tnsnames.ora" for m in zf.namelist())
    if not has_tns:
        raise HTTPException(
            status_code=400,
            detail={"error": "Wallet zip 에 tnsnames.ora 가 없습니다. ADB Wallet 파일이 맞는지 확인하세요."},
        )

    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)
    with zf:
        for member in zf.namelist():
            if member.endswith("/"):
                continue
            name = Path(member).name
            if not name:
                continue
            with zf.open(member) as src, open(dest / name, "wb") as out:
                shutil.copyfileobj(src, out)


def _entry(name: str, label: str, user: str, password: str, dsn: str, wallet_password: str) -> dict:
    rel = f"./wallets/{name}"
    return {
        "name": name,
        "label": label or name,
        "user": user,
        "password": password,
        "dsn": dsn,
        "wallet_location": rel,
        "wallet_password": wallet_password,
        "config_dir": rel,
    }


# ───────────────────────── 조회 ─────────────────────────
@router.get("/databases")
async def list_databases() -> list[dict]:
    cfg = deps.get_config()
    if cfg is None:
        return []
    return [
        {
            "name": d.name,
            "label": d.label,
            "status": "ok" if db.statuses.get(d.name) == "ok" else "unavailable",
            "is_default": cfg.default_database == d.name,
        }
        for d in cfg.databases
    ]


@router.get("/databases/{name}")
async def get_database(name: str) -> dict:
    cfg = deps.get_config()
    d = cfg.get(name) if cfg else None
    if d is None:
        raise HTTPException(status_code=404, detail={"error": "등록되지 않은 DB", "database": name})
    return _detail(d, is_default=cfg.default_database == name)


@router.post("/databases/parse-wallet")
async def parse_wallet(wallet: UploadFile = File(...)) -> dict:
    """Wallet zip 을 저장하지 않고 tnsnames.ora 만 읽어 DSN 별칭 목록을 돌려준다.

    등록 폼에서 파일 선택 직후 DSN 드롭다운을 채우는 용도."""
    data = await wallet.read()
    tns = _tnsnames_from_zip(data)
    if not tns:
        raise HTTPException(
            status_code=400,
            detail={"error": "Wallet zip 에서 tnsnames.ora 를 찾을 수 없습니다"},
        )
    return {"dsns": _parse_tns_aliases(tns)}


# ───────────────────────── 생성/수정/삭제 ─────────────────────────
@router.post("/databases")
async def create_database(
    name: str = Form(...),
    user: str = Form(...),
    password: str = Form(...),
    dsn: str = Form(...),
    label: str = Form(""),
    wallet_password: str = Form(""),
    wallet: UploadFile = File(...),
) -> dict:
    name = name.strip()
    if not _NAME_RE.match(name):
        raise HTTPException(
            status_code=400,
            detail={"error": "이름은 영문/숫자/_/- 만 사용할 수 있습니다", "database": name},
        )
    cfg = deps.get_config()
    if cfg and cfg.get(name):
        raise HTTPException(status_code=409, detail={"error": "이미 등록된 이름입니다", "database": name})

    data = await wallet.read()
    _extract_wallet(data, WALLETS_DIR / name)

    raw = load_raw()
    raw.setdefault("databases", [])
    raw["databases"].append(_entry(name, label, user, password, dsn, wallet_password))
    if not raw.get("default_database"):
        raw["default_database"] = name
    save_raw(raw)

    new_cfg = _reload_into_memory()
    d = new_cfg.get(name)
    err = await db.reinit_pool(d)
    return {"ok": True, "detail": _detail(d, new_cfg.default_database == name), "error": err}


@router.put("/databases/{name}")
async def update_database(
    name: str,
    user: str = Form(...),
    dsn: str = Form(...),
    label: str = Form(""),
    password: str = Form(""),
    wallet_password: str = Form(""),
    replace_wallet_password: bool = Form(False),
    wallet: UploadFile | None = File(None),
) -> dict:
    cfg = deps.get_config()
    existing = cfg.get(name) if cfg else None
    if existing is None:
        raise HTTPException(status_code=404, detail={"error": "등록되지 않은 DB", "database": name})

    # Wallet 파일이 새로 올라왔으면 교체
    if wallet is not None:
        data = await wallet.read()
        if data:
            _extract_wallet(data, WALLETS_DIR / name)

    raw = load_raw()
    target = next((e for e in raw.get("databases", []) if e.get("name") == name), None)
    if target is None:
        raise HTTPException(status_code=404, detail={"error": "config.yaml 에 항목이 없습니다", "database": name})

    target["label"] = label or name
    target["user"] = user
    target["dsn"] = dsn
    if password:  # 비우면 기존 비밀번호 유지
        target["password"] = password
    # wallet_password: 명시적 교체 플래그가 있을 때만 변경 (빈 값으로 지우기 포함)
    if replace_wallet_password:
        target["wallet_password"] = wallet_password
    save_raw(raw)

    new_cfg = _reload_into_memory()
    d = new_cfg.get(name)
    err = await db.reinit_pool(d)
    return {"ok": True, "detail": _detail(d, new_cfg.default_database == name), "error": err}


@router.delete("/databases/{name}")
async def delete_database(name: str) -> dict:
    cfg = deps.get_config()
    if cfg is None or cfg.get(name) is None:
        raise HTTPException(status_code=404, detail={"error": "등록되지 않은 DB", "database": name})
    if len(cfg.databases) <= 1:
        raise HTTPException(
            status_code=400,
            detail={"error": "마지막 DB 는 삭제할 수 없습니다 (최소 1개 필요)"},
        )

    raw = load_raw()
    raw["databases"] = [e for e in raw.get("databases", []) if e.get("name") != name]
    if raw.get("default_database") == name:
        raw["default_database"] = raw["databases"][0]["name"] if raw["databases"] else ""
    save_raw(raw)

    await db.drop_pool(name)
    wallet_dir = WALLETS_DIR / name
    if wallet_dir.exists():
        shutil.rmtree(wallet_dir, ignore_errors=True)

    _reload_into_memory()
    return {"ok": True}


@router.post("/databases/{name}/test")
async def test_database(name: str) -> dict:
    cfg = deps.get_config()
    d = cfg.get(name) if cfg else None
    if d is None:
        raise HTTPException(status_code=404, detail={"error": "등록되지 않은 DB", "database": name})
    err = await db.reinit_pool(d)
    return {"ok": err is None, "status": db.statuses.get(name, "unavailable"), "error": err}
