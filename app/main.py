"""FastAPI 엔트리 — 다중 ADB 풀 초기화 + static / API 라우팅."""
from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import auth, db, deps
from app.config import load_config
from app.routers import agents, asta_proxy, auth as auth_router, chat, databases, objects, profiles

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")

# 프로젝트 루트(project/) — app/ 의 부모
PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = PROJECT_ROOT / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = load_config()
    deps.set_config(cfg)
    # 풀 병렬 초기화 — 한 항목 실패가 다른 항목을 막지 않음
    await asyncio.gather(*(db.init_pool(d) for d in cfg.databases))
    try:
        yield
    finally:
        await db.close_all()


app = FastAPI(title="Oracle AI Database Test Tool", lifespan=lifespan)

# Content-Security-Policy — script 는 self + Chart.js CDN 만 허용하고 'unsafe-inline' 을
# 주지 않는다. 이 도구는 인라인 <script>·인라인 이벤트핸들러(onclick 등)를 쓰지 않으므로,
# DB/LLM 값이 innerHTML 로 주입돼도 인라인 핸들러 기반 XSS 실행이 차단된다(심층 방어).
# style 은 인라인 style="" 속성을 광범위하게 쓰므로 'unsafe-inline' 이 필요(스크립트보다 위험 낮음).
_CSP = (
    "default-src 'self'; "
    "script-src 'self' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "font-src 'self'; "
    "connect-src 'self' https://YH0OLYBN5PQCE4N-DEVDOADB.adb.ap-seoul-1.oraclecloudapps.com; "
    "frame-ancestors 'none'; "
    "base-uri 'none'; "
    "form-action 'self'; "
    "object-src 'none'"
)
_SECURITY_HEADERS = {
    "Content-Security-Policy": _CSP,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Permissions-Policy": "geolocation=(), camera=(), microphone=()",
}


def _is_https(request: Request) -> bool:
    fwd = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip().lower()
    return fwd == "https" or request.url.scheme == "https"


def _harden(request: Request, response) -> None:
    for k, v in _SECURITY_HEADERS.items():
        response.headers.setdefault(k, v)
    # HTTPS(또는 LB 뒤)에서는 HSTS 추가 — HTTP 직접배포에서는 브라우저가 무시.
    if _is_https(request):
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    # 민감 데이터가 담기는 API 응답과 자주 바뀌는 UI/JS는 캐시 금지.
    if request.url.path.startswith("/api/") or request.url.path == "/" or request.url.path.startswith("/static/js/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"


@app.middleware("http")
async def access_gate(request: Request, call_next):
    """사전공유 키 게이트 + 보안 헤더.

    - access_key 설정 시 /api/* 를 쿠키로 보호(`/`·`/static/*` 는 공개 — OCI LB 헬스체크 유지).
      auth.OPEN_API(login/logout/status/recover)는 예외. 키 미설정 시 전부 통과(부트스트랩).
    - 모든 응답(401 포함)에 보안 헤더를 부착한다.
    """
    path = request.url.path
    if (
        auth.is_enabled()
        and path.startswith("/api/")
        and path not in auth.OPEN_API
    ):
        token = request.cookies.get(auth.COOKIE_NAME)
        if not auth.verify_token(auth.current_access_key(), token, time.time()):
            resp = JSONResponse({"error": "unauthorized"}, status_code=401)
            _harden(request, resp)
            return resp
    response = await call_next(request)
    _harden(request, response)
    return response


app.include_router(auth_router.router, prefix="/api")
app.include_router(databases.router, prefix="/api")
app.include_router(profiles.router, prefix="/api")
app.include_router(agents.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
app.include_router(objects.router, prefix="/api")
app.include_router(asta_proxy.router, prefix="/api")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
