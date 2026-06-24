"""사전공유 키 기반 접근제어 — HMAC 서명 쿠키 헬퍼 (DB·세션 테이블 없음).

모델: config.yaml 의 단일 access_key 1개. 사용자가 키를 입력하면(/api/auth/login)
HMAC 서명 토큰을 쿠키로 발급해 로그인을 유지한다. 쿠키 서명 비밀은 access_key
에서 파생하므로 키를 바꾸면 기존 쿠키가 모두 무효화된다(= 키 회전 시 전원 재로그인).

access_key 가 비어 있으면 인증 비활성(is_enabled()==False) — 로컬 개발/초기 부트스트랩.
순수 헬퍼 모듈로, DB 에 접근하지 않는다.
"""
from __future__ import annotations

import base64
import hmac
from hashlib import sha256

from app import deps

COOKIE_NAME = "oai_auth"
AUTH_TTL = 7 * 24 * 3600  # 7일

# 인증 게이트를 통과시켜야 하는(= 쿠키 없이 호출 가능한) /api 경로.
# 키 관리용 GET/PUT /api/auth/key, /admin-email 은 여기에 넣지 않는다(보호 대상).
# /recover 는 로그인 화면(미인증)에서 호출하므로 공개 — 단, 키는 요청자에게 노출하지
# 않고 설정된 관리자 이메일로만 발송된다.
OPEN_API = {
    "/api/auth/login",
    "/api/auth/logout",
    "/api/auth/status",
    "/api/auth/recover",
}


def current_access_key() -> str:
    cfg = deps.get_config()
    return cfg.access_key if cfg else ""


def is_enabled() -> bool:
    """access_key 가 설정되어 있으면 인증 활성."""
    return bool(current_access_key())


def verify_password(supplied: str, access_key: str) -> bool:
    """입력 키와 설정 키를 타이밍 안전하게 비교."""
    if not access_key:
        return False
    return hmac.compare_digest(supplied.encode("utf-8"), access_key.encode("utf-8"))


def _cookie_secret(access_key: str) -> bytes:
    return hmac.new(access_key.encode("utf-8"), b"oai-cookie-v1", sha256).digest()


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _sig(access_key: str, exp: int) -> str:
    mac = hmac.new(_cookie_secret(access_key), str(exp).encode("ascii"), sha256).digest()
    return _b64(mac)


def sign_token(access_key: str, now: float) -> str:
    """exp.<서명> 형태의 토큰을 만든다. now 는 time.time()."""
    exp = int(now) + AUTH_TTL
    return f"{exp}.{_sig(access_key, exp)}"


def verify_token(access_key: str, token: str | None, now: float) -> bool:
    """토큰 서명·만료 검증. access_key 가 비면 항상 False(호출 측에서 비활성 분기)."""
    if not access_key or not token or "." not in token:
        return False
    exp_str, sig = token.split(".", 1)
    try:
        exp = int(exp_str)
    except ValueError:
        return False
    if exp <= int(now):
        return False
    return hmac.compare_digest(sig, _sig(access_key, exp))
