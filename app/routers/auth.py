"""접근제어 API — 사전공유 키 로그인 + 키 관리 (DB·세션 테이블 없음).

- POST /login   : 키 검증 → HMAC 서명 쿠키 발급
- POST /logout  : 쿠키 삭제
- GET  /status  : 인증 활성/로그인 여부
- GET  /key     : (보호) 현재 키 평문 반환 — 관리자가 사용자에게 배포용
- PUT  /key     : (보호/부트스트랩) 키 설정·회전 → config.yaml 재기록 + 자동 로그인 쿠키

GET/PUT /key 는 auth.OPEN_API 에 없으므로, 키가 설정된 뒤에는 main.py 의 미들웨어가
쿠키를 요구한다. 키 미설정(is_enabled()==False) 단계에서는 미들웨어가 전부 통과시켜
첫 키 설정(부트스트랩)이 가능하다.
"""
from __future__ import annotations

import asyncio
import re
import time

from fastapi import APIRouter, HTTPException, Request, Response

from app import auth, deps, mailer, ratelimit
from app.config import load_config, load_raw, save_raw

router = APIRouter(prefix="/auth", tags=["auth"])

MIN_KEY_LEN = 8
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _mask_email(email: str) -> str:
    """a***@example.com 형태로 마스킹 (요청자에게 전체 주소를 노출하지 않음)."""
    try:
        local, domain = email.split("@", 1)
    except ValueError:
        return "***"
    head = local[0] if local else ""
    return f"{head}***@{domain}"


def _is_secure(request: Request) -> bool:
    # LB(TLS 종단) 뒤에서는 앱이 보는 scheme 이 http 이므로 X-Forwarded-Proto 로 판정.
    fwd = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip().lower()
    return fwd == "https" or request.url.scheme == "https"


def _set_auth_cookie(request: Request, response: Response, access_key: str) -> None:
    token = auth.sign_token(access_key, time.time())
    response.set_cookie(
        key=auth.COOKIE_NAME,
        value=token,
        max_age=auth.AUTH_TTL,
        httponly=True,
        samesite="lax",
        secure=_is_secure(request),
        path="/",
    )


@router.post("/login")
async def login(payload: dict, request: Request, response: Response) -> dict:
    access_key = auth.current_access_key()
    if not access_key:
        # 인증 비활성 — 로그인 불필요
        return {"ok": True, "disabled": True}
    # 무차별 대입 완화 — IP 당 5분에 10회.
    if not ratelimit.check(f"login:{_client_ip(request)}", 10, 300):
        raise HTTPException(
            status_code=429,
            detail={"error": "로그인 시도가 너무 많습니다. 잠시 후 다시 시도하세요."},
        )
    key = (payload.get("key") or "").strip()
    if not key or not auth.verify_password(key, access_key):
        raise HTTPException(status_code=401, detail={"error": "접근 키가 올바르지 않습니다"})
    _set_auth_cookie(request, response, access_key)
    return {"ok": True}


@router.post("/logout")
async def logout(response: Response) -> dict:
    response.delete_cookie(key=auth.COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/status")
async def status(request: Request) -> dict:
    cfg = deps.get_config()
    access_key = cfg.access_key if cfg else ""
    enabled = bool(access_key)
    authenticated = (not enabled) or auth.verify_token(
        access_key, request.cookies.get(auth.COOKIE_NAME), time.time()
    )
    # 키 분실 신고 가능 여부 — 키가 설정되어 있고 관리자 이메일이 등록된 경우.
    recoverable = bool(enabled and cfg and cfg.admin_email)
    return {"enabled": enabled, "authenticated": authenticated, "recoverable": recoverable}


@router.get("/key")
async def get_key() -> dict:
    """현재 키 평문 + 관리자 이메일. 인증 활성 시 미들웨어가 보호하므로 로그인한 관리자만 도달한다."""
    cfg = deps.get_config()
    access_key = cfg.access_key if cfg else ""
    return {
        "set": bool(access_key),
        "key": access_key or None,
        "admin_email": (cfg.admin_email if cfg else "") or "",
    }


@router.put("/admin-email")
async def set_admin_email(payload: dict) -> dict:
    """키 분실 복구용 관리자 이메일 설정/해제. 빈 값이면 해제."""
    email = (payload.get("email") or "").strip()
    if email and not EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail={"error": "올바른 이메일 형식이 아닙니다"})
    raw = load_raw()
    raw["admin_email"] = email
    save_raw(raw)
    deps.set_config(load_config())
    return {"ok": True, "admin_email": email}


@router.post("/recover")
async def recover(request: Request) -> dict:
    """로그인 화면의 '키 분실 신고' — 현재 키를 관리자 이메일로 발송.

    키는 요청자에게 반환하지 않고, 설정된 관리자 이메일로만 보낸다(요청자 ≠ 수신자).
    """
    # 메일 스팸 완화 — IP 당 10분에 3회.
    if not ratelimit.check(f"recover:{_client_ip(request)}", 3, 600):
        raise HTTPException(
            status_code=429,
            detail={"error": "요청이 너무 많습니다. 잠시 후 다시 시도하세요."},
        )
    cfg = deps.get_config()
    if not (cfg and cfg.access_key):
        raise HTTPException(status_code=400, detail={"error": "설정된 접근 키가 없습니다"})
    if not cfg.admin_email:
        raise HTTPException(
            status_code=400,
            detail={"error": "관리자 이메일이 설정되지 않았습니다. 관리자에게 직접 문의하세요."},
        )
    try:
        await asyncio.to_thread(mailer.send_key_email, cfg.smtp or {}, cfg.admin_email, cfg.access_key)
    except Exception as exc:
        msg = str(exc).strip().splitlines()[0] if str(exc).strip() else "메일 발송 실패"
        raise HTTPException(status_code=502, detail={"error": f"메일 발송 실패: {msg}"})
    return {"ok": True, "sent_to": _mask_email(cfg.admin_email)}


@router.put("/key")
async def set_key(payload: dict, request: Request, response: Response) -> dict:
    key = (payload.get("key") or "").strip()
    if len(key) < MIN_KEY_LEN:
        raise HTTPException(
            status_code=400,
            detail={"error": f"접근 키는 최소 {MIN_KEY_LEN}자 이상이어야 합니다"},
        )
    raw = load_raw()
    raw["access_key"] = key
    save_raw(raw)
    deps.set_config(load_config())
    # 새 키로 서명한 쿠키 발급 — 키를 설정한 관리자는 곧바로 로그인 상태가 된다.
    _set_auth_cookie(request, response, key)
    return {"ok": True, "set": True}
