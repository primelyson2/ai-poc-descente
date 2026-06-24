"""다중 ADB 비동기 풀 관리 (python-oracledb Thin mode + Wallet/mTLS).

- pools: DB 이름 → AsyncConnectionPool
- statuses: DB 이름 → 'ok' | 'unavailable'   (실패한 풀도 상태로 노출)
- init_pool 한 항목 실패가 다른 항목을 막지 않는다.
- fetch_all / fetch_one / execute 헬퍼는 CLOB 을 자동으로 문자열화한다.
"""
from __future__ import annotations

import logging
from typing import Any

import oracledb

from app.config import DatabaseConfig

logger = logging.getLogger(__name__)

# CLOB 을 fetch 시점에 inline 문자열로 받아온다 (값마다 별도 lob.read() 왕복 제거).
# 트리/타임라인 쿼리는 attribute_value/description 등 CLOB 컬럼이 많아, 이 설정이
# 가장 큰 성능 개선 포인트다. (큰 LOB 스트리밍이 필요한 경우는 본 PoC 에 없음)
oracledb.defaults.fetch_lobs = False

pools: dict[str, oracledb.AsyncConnectionPool] = {}
statuses: dict[str, str] = {}


async def _open_pool(db: DatabaseConfig) -> oracledb.AsyncConnectionPool:
    kwargs: dict[str, Any] = {
        "user": db.user,
        "password": db.password,
        "dsn": db.dsn,
        "min": 1,
        "max": 8,
        "increment": 1,
    }
    if db.wallet_location:
        kwargs["wallet_location"] = db.wallet_location
    if db.wallet_password:
        kwargs["wallet_password"] = db.wallet_password
    if db.config_dir:
        kwargs["config_dir"] = db.config_dir
    pool = oracledb.create_pool_async(**kwargs)
    # ping 으로 실제 연결 검증
    async with pool.acquire() as conn:
        await conn.ping()
    return pool


async def reinit_pool(db: DatabaseConfig) -> str | None:
    """기존 풀이 있으면 닫고 다시 초기화. 성공 시 None, 실패 시 오류 메시지를 반환.

    런타임에 새 DB 를 등록/수정할 때 사용한다. 실패해도 status 만 'unavailable'
    로 바꾸고 오류 문자열을 돌려주어 호출자가 사용자에게 노출할 수 있게 한다.
    """
    old = pools.pop(db.name, None)
    if old is not None:
        try:
            await old.close(force=True)
        except Exception:
            logger.exception("DB pool close failed before reinit: %s", db.name)
    try:
        pool = await _open_pool(db)
        pools[db.name] = pool
        statuses[db.name] = "ok"
        logger.info("DB pool ready: %s", db.name)
        return None
    except Exception as exc:
        statuses[db.name] = "unavailable"
        logger.exception("DB pool init failed for %s: %s", db.name, exc)
        return str(exc)


async def init_pool(db: DatabaseConfig) -> None:
    """단일 DB 풀 초기화 + ping 검증. 실패 시 status='unavailable'."""
    await reinit_pool(db)


async def drop_pool(name: str) -> None:
    """풀을 닫고 pools/statuses 에서 제거 (DB 등록 해제 시)."""
    old = pools.pop(name, None)
    if old is not None:
        try:
            await old.close(force=True)
        except Exception:
            logger.exception("DB pool close failed: %s", name)
    statuses.pop(name, None)


async def close_all() -> None:
    for name, pool in list(pools.items()):
        try:
            await pool.close(force=True)
        except Exception:
            logger.exception("DB pool close failed: %s", name)
    pools.clear()
    statuses.clear()


def get_pool(db_name: str) -> oracledb.AsyncConnectionPool:
    if db_name not in pools:
        raise KeyError(db_name)
    return pools[db_name]


async def fetch_all(db_name: str, sql: str, **binds: Any) -> list[dict]:
    # fetch_lobs=False (모듈 상단) 덕에 CLOB 은 이미 str 로 들어온다 — 별도 read() 불필요.
    pool = get_pool(db_name)
    async with pool.acquire() as conn:
        with conn.cursor() as cur:
            await cur.execute(sql, binds)
            cols = [d[0].lower() for d in (cur.description or [])]
            rows = await cur.fetchall()
            return [dict(zip(cols, row)) for row in rows]


async def fetch_one(db_name: str, sql: str, **binds: Any) -> dict | None:
    pool = get_pool(db_name)
    async with pool.acquire() as conn:
        with conn.cursor() as cur:
            await cur.execute(sql, binds)
            cols = [d[0].lower() for d in (cur.description or [])]
            row = await cur.fetchone()
            if row is None:
                return None
            return dict(zip(cols, row))


async def execute(db_name: str, sql: str, **binds: Any) -> None:
    pool = get_pool(db_name)
    async with pool.acquire() as conn:
        with conn.cursor() as cur:
            await cur.execute(sql, binds)
        await conn.commit()
